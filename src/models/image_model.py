from pathlib import Path

from PIL import Image, ImageOps
from send2trash import send2trash

from . import metadata

# Las fotos del iPhone son HEIC: Pillow no las abre sin este registro.
try:
  from pillow_heif import register_heif_opener

  register_heif_opener()
  HEIF_EXTENSIONS = (".heic", ".heif")
except ImportError:
  HEIF_EXTENSIONS = ()

# Formatos que aceptamos en el dialogo de apertura.
SUPPORTED_EXTENSIONS = (
  ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", *HEIF_EXTENSIONS
)

# Criterios de orden de la lista de archivos.
SORT_NAME = "name"
SORT_SIZE = "size"
SORT_MODIFIED = "modified"

# Lado maximo de las miniaturas de la grilla.
THUMBNAIL_BOX = 240
THUMBNAIL_CACHE_LIMIT = 200
# Tope de miniaturas a generar: mas alla la grilla deja de ser legible y el
# coste de leerlas del disco se nota al redibujar.
MAX_GRID_ITEMS = 36

# Grados en sentido horario -> operacion de Pillow. transpose es exacto y
# barato: no reinterpola pixeles como lo haria rotate().
_ROTATIONS = {
  90: Image.Transpose.ROTATE_270,
  180: Image.Transpose.ROTATE_180,
  270: Image.Transpose.ROTATE_90,
}


class ImageModel:
  """Mantiene la imagen abierta, sus vecinas de carpeta, y notifica los cambios."""

  def __init__(self, preferences=None):
    # Sin repositorio el modelo funciona igual, solo sin recordar rotaciones.
    self._preferences = preferences
    self._path = None
    self._image = None
    self._rotation = 0
    self._rotated = None
    self._metadata = []
    self._directory = None
    self._files = []
    # El orden no se recuerda entre sesiones: cada arranque empieza por nombre.
    self._sort_key = SORT_NAME
    self._sort_descending = False
    self._thumbnail_cache = {}
    self._observers = []

  @property
  def path(self):
    return self._path

  @property
  def image(self):
    """La imagen como debe verse: el original mas la rotacion de la sesion."""
    if self._image is None or self._rotation == 0:
      return self._image
    if self._rotated is None:
      self._rotated = self._image.transpose(_ROTATIONS[self._rotation])
    return self._rotated

  @property
  def rotation(self):
    return self._rotation

  @property
  def has_image(self):
    return self._image is not None

  @property
  def size(self):
    return self.image.size if self._image else None

  @property
  def metadata(self):
    """Secciones [(titulo, [(campo, valor), ...])] de la imagen abierta."""
    return self._metadata

  @property
  def files(self):
    """Imagenes soportadas que viven en la misma carpeta que la abierta."""
    return list(self._files)

  @property
  def index(self):
    """Posicion de la imagen actual dentro de files (-1 si no hay ninguna)."""
    if self._path is None:
      return -1
    try:
      return self._files.index(self._path)
    except ValueError:
      return -1

  def subscribe(self, callback):
    """Registra un callback que se ejecuta cada vez que cambia la imagen."""
    self._observers.append(callback)

  def load(self, path):
    """Carga la imagen desde disco. Lanza OSError si el archivo no es valido."""
    path = Path(path).resolve()
    image = Image.open(path)
    image.load()
    # Las fotos de camara/movil guardan la rotacion en el EXIF: la aplicamos.
    image = ImageOps.exif_transpose(image)

    # Solo releemos el disco al cambiar de carpeta, no al saltar entre vecinas.
    if path.parent != self._directory:
      self._directory = path.parent
      self._files = self._sorted(scan_folder(path.parent))

    # Un archivo con extension fuera de la lista igual merece estar visible.
    if path not in self._files:
      self._files = self._sorted([*self._files, path])

    self._path = path
    self._image = image
    # Recuperamos la rotacion que el usuario dejo la ultima vez. Los metadatos
    # siguen describiendo el archivo en disco, no como lo estemos viendo.
    self._rotation = self._preferences.rotation_for(path) if self._preferences else 0
    self._rotated = None
    self._metadata = metadata.extract(path, image)
    self._notify()

  def set_sort(self, key, descending):
    """Reordena la carpeta. Cambia tambien el orden de navegacion con flechas."""
    self._sort_key = key
    self._sort_descending = descending
    self._files = self._sorted(self._files)
    self._notify()

  def _sorted(self, files):
    return sorted(
      files,
      key=lambda path: sort_value(path, self._sort_key),
      reverse=self._sort_descending,
    )

  def rotate(self, degrees):
    """Gira la presentacion en multiplos de 90. No modifica el archivo."""
    if self._image is None:
      return
    self._rotation = (self._rotation + degrees) % 360
    self._rotated = None
    # La miniatura de la grilla lleva la rotacion aplicada: queda obsoleta.
    self._thumbnail_cache.pop(self._path, None)
    if self._preferences:
      self._preferences.save_rotation(self._path, self._rotation)
    self._notify()

  def rename(self, new_name):
    """Renombra el archivo abierto conservando su extension.

    Lanza ValueError si el nombre no sirve y FileExistsError si la carpeta ya
    tiene otro archivo asi: nunca sobrescribimos en silencio.
    """
    if self._path is None:
      return None

    new_name = new_name.strip()
    if not new_name:
      raise ValueError("El nombre no puede estar vacio.")
    if any(character in new_name for character in ("/", "\\", "\0")):
      raise ValueError("El nombre no puede contener / ni \\.")

    target = self._path.with_name(new_name + self._path.suffix)
    if target == self._path:
      return self._path

    # samefile evita el falso positivo al cambiar solo mayusculas: en macOS
    # «foto.png» y «Foto.png» son el mismo archivo para el sistema.
    if target.exists() and not target.samefile(self._path):
      raise FileExistsError(f"Ya existe «{target.name}» en la carpeta.")

    previous = self._path
    previous.rename(target)
    self._thumbnail_cache.pop(previous, None)

    # La rotacion guardada esta indexada por ruta: la mudamos con el archivo.
    if self._preferences and self._rotation:
      self._preferences.forget(previous)
      self._preferences.save_rotation(target, self._rotation)

    self._files = self._sorted([item for item in self._files if item != previous] + [target])
    self._path = target
    self._metadata = metadata.extract(target, self._image)
    self._notify()
    return target

  def thumbnails(self, paths, box=THUMBNAIL_BOX):
    """Miniaturas [(nombre, imagen)] para la grilla, con la rotacion aplicada.

    Se cachean por ruta: la grilla se redibuja en cada resize y releer el
    disco cada vez seria inaceptable.
    """
    items = []
    for path in paths:
      thumbnail = self._thumbnail_cache.get(path)
      if thumbnail is None:
        thumbnail = self._build_thumbnail(path, box)
        if thumbnail is None:
          continue
        # Tope simple para que la cache no crezca sin limite en carpetas grandes.
        if len(self._thumbnail_cache) > THUMBNAIL_CACHE_LIMIT:
          self._thumbnail_cache.clear()
        self._thumbnail_cache[path] = thumbnail
      items.append((path.name, thumbnail))
    return items

  def _build_thumbnail(self, path, box):
    try:
      with Image.open(path) as source:
        # draft deja que el decodificador JPEG salte a una escala menor: es
        # varias veces mas rapido que decodificar entero y luego reducir.
        source.draft("RGB", (box, box))
        image = ImageOps.exif_transpose(source)
        image = image.convert("RGBA") if image.mode not in ("RGB", "RGBA", "L") else image
        rotation = self._preferences.rotation_for(path) if self._preferences else 0
        if rotation:
          image = image.transpose(_ROTATIONS[rotation])
        image.thumbnail((box, box), Image.LANCZOS)
        return image
    except (OSError, ValueError):
      return None

  def send_to_trash(self, paths=None):
    """Manda a la papelera las rutas dadas, o la imagen abierta si no hay.

    Devuelve (siguiente_a_abrir, fallidas). No abre nada: eso lo decide el
    controlador, que es quien sabe como reportar un fallo de lectura.
    """
    targets = list(paths) if paths else ([self._path] if self._path else [])
    if not targets:
      return None, []

    index = max(self.index, 0)
    removed = []
    failed = []
    for target in targets:
      try:
        send2trash(target)
      except OSError:
        # Una que falla no debe abortar el resto del lote.
        failed.append(target.name)
        continue
      removed.append(target)
      if self._preferences:
        self._preferences.forget(target)
      self._thumbnail_cache.pop(target, None)

    self._files = [item for item in self._files if item not in set(removed)]
    if not self._files:
      return None, failed

    # Si la imagen abierta sobrevivio al lote, seguimos en ella. Si no, esa
    # posicion ya la ocupa la siguiente; y si borramos la ultima, la anterior.
    if self._path in self._files:
      return self._path, failed
    return self._files[min(index, len(self._files) - 1)], failed

  def load_at(self, index):
    """Carga la imagen que ocupa esa posicion en files."""
    if 0 <= index < len(self._files):
      self.load(self._files[index])

  def clear(self):
    self._path = None
    self._image = None
    self._rotation = 0
    self._rotated = None
    self._metadata = []
    self._directory = None
    self._files = []
    self._thumbnail_cache.clear()
    self._notify()

  def _notify(self):
    for callback in self._observers:
      callback(self)


def sort_value(path, key):
  """Valor por el que ordenar una imagen segun el criterio elegido."""
  if key != SORT_NAME:
    try:
      stat = path.stat()
    except OSError:
      # Archivo desaparecido entre el escaneo y el orden: al final de la lista.
      return 0
    return stat.st_size if key == SORT_SIZE else stat.st_mtime
  return path.name.lower()


def scan_folder(directory):
  """Imagenes soportadas de una carpeta, ordenadas por nombre."""
  try:
    entries = [
      entry
      for entry in Path(directory).iterdir()
      if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
  except OSError:
    # Carpeta sin permisos o desmontada: seguimos con la imagen ya abierta.
    return []
  return sorted(entries, key=_sort_key)


def _sort_key(path):
  return path.name.lower()
