from pathlib import Path

from PIL import Image, ImageOps

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

# Grados en sentido horario -> operacion de Pillow. transpose es exacto y
# barato: no reinterpola pixeles como lo haria rotate().
_ROTATIONS = {
  90: Image.Transpose.ROTATE_270,
  180: Image.Transpose.ROTATE_180,
  270: Image.Transpose.ROTATE_90,
}


class ImageModel:
  """Mantiene la imagen abierta, sus vecinas de carpeta, y notifica los cambios."""

  def __init__(self):
    self._path = None
    self._image = None
    self._rotation = 0
    self._rotated = None
    self._metadata = []
    self._directory = None
    self._files = []
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
      self._files = self._scan(path.parent)

    # Un archivo con extension fuera de la lista igual merece estar visible.
    if path not in self._files:
      self._files = sorted([*self._files, path], key=_sort_key)

    self._path = path
    self._image = image
    # Cada imagen empieza sin rotar; los metadatos describen el archivo tal
    # como esta en disco, no como lo estemos viendo.
    self._rotation = 0
    self._rotated = None
    self._metadata = metadata.extract(path, image)
    self._notify()

  def rotate(self, degrees):
    """Gira la presentacion en multiplos de 90. No modifica el archivo."""
    if self._image is None:
      return
    self._rotation = (self._rotation + degrees) % 360
    self._rotated = None
    self._notify()

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
    self._notify()

  def _scan(self, directory):
    try:
      entries = [
        entry
        for entry in directory.iterdir()
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS
      ]
    except OSError:
      # Carpeta sin permisos o desmontada: seguimos con la imagen ya abierta.
      return []
    return sorted(entries, key=_sort_key)

  def _notify(self):
    for callback in self._observers:
      callback(self)


def _sort_key(path):
  return path.name.lower()
