"""Extraccion de metadatos del archivo de imagen.

Todo sale de la libreria estandar y de Pillow: no hace falta nada mas para
fecha de creacion, formato, dimensiones ni EXIF de camara.
"""

from datetime import datetime
from math import gcd

from PIL import ExifTags, Image

DATE_FORMAT = "%d/%m/%Y %H:%M:%S"

# Etiquetas EXIF de camara que vale la pena mostrar, en orden de lectura.
_CAMERA_TAGS = (
  ("Make", "Marca"),
  ("Model", "Modelo"),
  ("LensModel", "Lente"),
  ("DateTimeOriginal", "Captura"),
  ("ExposureTime", "Exposición"),
  ("FNumber", "Apertura"),
  ("ISOSpeedRatings", "ISO"),
  ("FocalLength", "Focal"),
  ("Software", "Software"),
)


def extract(path, image):
  """Devuelve [(titulo_seccion, [(campo, valor), ...]), ...]."""
  exif = _read_exif(path)
  sections = [
    ("Archivo", _file_rows(path)),
    ("Imagen", _image_rows(path, image)),
    ("Cámara", _camera_rows(exif)),
    ("Ubicación GPS", _gps_rows(exif)),
  ]
  return [(title, rows) for title, rows in sections if rows]


# --- Secciones ---


def _file_rows(path):
  try:
    stat = path.stat()
  except OSError:
    return [("Nombre", path.name)]

  # st_birthtime es la fecha de creacion real; solo existe en macOS y BSD.
  created = getattr(stat, "st_birthtime", None)

  rows = [("Nombre", path.name), ("Carpeta", str(path.parent))]
  if created:
    rows.append(("Creado", _format_date(created)))
  rows.append(("Modificado", _format_date(stat.st_mtime)))
  rows.append(("Peso", format_size(stat.st_size)))
  return rows


def _image_rows(path, image):
  width, height = image.size
  rows = [
    ("Dimensiones", f"{width} x {height} px"),
    ("Proporción", _format_ratio(width, height)),
    ("Color", image.mode),
  ]

  try:
    with Image.open(path) as source:
      rows.insert(0, ("Formato", source.format or path.suffix.lstrip(".").upper()))
      dpi = source.info.get("dpi")
      if dpi:
        rows.append(("Resolución", f"{round(dpi[0])} x {round(dpi[1])} ppp"))
      frames = getattr(source, "n_frames", 1)
      if frames > 1:
        rows.append(("Fotogramas", str(frames)))
  except OSError:
    pass

  return rows


def _camera_rows(exif):
  if not exif:
    return []

  rows = []
  for tag, label in _CAMERA_TAGS:
    value = exif.get(tag)
    if value in (None, ""):
      continue
    rows.append((label, _format_camera_value(tag, value)))
  return rows


def _gps_rows(exif):
  gps = exif.get("_gps")
  if not gps:
    return []

  latitude = _to_degrees(gps.get(2), gps.get(1), ("S",))
  longitude = _to_degrees(gps.get(4), gps.get(3), ("W",))
  if latitude is None or longitude is None:
    return []

  rows = [("Coordenadas", f"{latitude:.6f}, {longitude:.6f}")]
  altitude = gps.get(6)
  if altitude is not None:
    rows.append(("Altitud", f"{float(altitude):.0f} m"))
  return rows


# --- Lectura EXIF ---


def _read_exif(path):
  """Aplana el EXIF principal y el IFD anidado en un dict por nombre de tag."""
  try:
    with Image.open(path) as source:
      raw = source.getexif()
      if not raw:
        return {}

      flat = {ExifTags.TAGS.get(tag, tag): value for tag, value in raw.items()}

      # Los datos de disparo (ISO, apertura) viven en un IFD aparte.
      details = raw.get_ifd(ExifTags.IFD.Exif)
      flat.update({ExifTags.TAGS.get(tag, tag): value for tag, value in details.items()})

      gps = raw.get_ifd(ExifTags.IFD.GPSInfo)
      if gps:
        flat["_gps"] = gps

      return flat
  except (OSError, AttributeError, ValueError):
    return {}


# --- Formateo ---


def _format_camera_value(tag, value):
  try:
    if tag == "ExposureTime":
      seconds = float(value)
      return f"{seconds:.1f} s" if seconds >= 1 else f"1/{round(1 / seconds)} s"
    if tag == "FNumber":
      return f"f/{float(value):.1f}"
    if tag == "FocalLength":
      return f"{float(value):.0f} mm"
    if tag == "ISOSpeedRatings":
      return f"ISO {int(value)}"
    if tag == "DateTimeOriginal":
      return _format_exif_date(value)
  except (TypeError, ValueError, ZeroDivisionError):
    pass
  return str(value).strip()


def _format_exif_date(value):
  try:
    return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S").strftime(DATE_FORMAT)
  except ValueError:
    return str(value)


def _format_date(timestamp):
  return datetime.fromtimestamp(timestamp).strftime(DATE_FORMAT)


def format_size(size):
  for unit in ("B", "KB", "MB", "GB"):
    if size < 1024 or unit == "GB":
      return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
    size /= 1024
  return f"{size:.1f} GB"


def format_short_date(timestamp):
  """Fecha compacta para la tabla de archivos."""
  return datetime.fromtimestamp(timestamp).strftime("%d/%m/%y")


def _format_ratio(width, height):
  divisor = gcd(width, height) or 1
  simple = (width // divisor, height // divisor)
  # Una relacion como 1237:811 no le dice nada a nadie: mejor aproximarla.
  if max(simple) > 30:
    return f"{width / height:.2f}:1"
  return f"{simple[0]}:{simple[1]}"


def _to_degrees(value, reference, negatives):
  """Convierte (grados, minutos, segundos) del EXIF a grados decimales."""
  if not value:
    return None
  try:
    degrees, minutes, seconds = (float(part) for part in value)
  except (TypeError, ValueError):
    return None

  decimal = degrees + minutes / 60 + seconds / 3600
  return -decimal if str(reference).upper() in negatives else decimal
