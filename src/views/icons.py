"""Iconos de la interfaz.

Se resuelven de dos formas: un archivo de imagen dentro de src/icons, o un SVG
embebido que Tk 9 rasteriza de forma nativa. Si ninguna funciona (por ejemplo
en Tk 8.6, sin soporte SVG) los botones se quedan solo con texto.
"""

import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

ICON_SIZE = 18
ICON_COLOR = "#3b6fd4"
VIEWBOX = 24
ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"

_TEMPLATE = (
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {box} {box}" fill="none" '
  'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
  "{body}</svg>"
)

_PATHS = {
  "folder": (
    '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9'
    'A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>'
  ),
}

# Guarda las imagenes vivas: tkinter no retiene la referencia por si solo.
_cache = {}


def load(name, size=ICON_SIZE, color=ICON_COLOR, tint=None):
  """Devuelve un PhotoImage con el icono, o None si no se pudo resolver.

  tint recolorea el glifo conservando su transparencia, util para iconos
  negros sobre un boton de color.
  """
  key = (name, size, color, tint)
  if key in _cache:
    return _cache[key]

  image = _load_file(name, size, tint)
  if image is None:
    image = _load_svg(name, size, tint or color)

  if image is not None:
    _cache[key] = image
  return image


def _load_file(name, size, tint=None):
  """Carga un archivo de src/icons y lo ajusta al tamano del boton."""
  path = ICONS_DIR / name
  if not path.suffix or not path.is_file():
    return None

  try:
    with Image.open(path) as source:
      icon = source.convert("RGBA")
      # thumbnail respeta la proporcion y nunca amplia mas alla del original.
      icon.thumbnail((size, size), Image.LANCZOS)
      if tint:
        icon = _tinted(icon, tint)
      return ImageTk.PhotoImage(icon)
  except OSError:
    return None


def _tinted(icon, color):
  """Pinta el glifo de un color plano usando su canal alfa como mascara."""
  solid = Image.new("RGBA", icon.size, color)
  solid.putalpha(icon.getchannel("A"))
  return solid


def _load_svg(name, size, color):
  body = _PATHS.get(name)
  if body is None:
    return None

  svg = _TEMPLATE.format(box=VIEWBOX, color=color, body=body)
  try:
    return tk.PhotoImage(data=svg, format=f"svg -scale {size / VIEWBOX}")
  except tk.TclError:
    return None


