"""Iconos SVG embebidos.

Tk 9 rasteriza SVG de forma nativa, asi que no hacen falta archivos de imagen
ni dependencias extra. En Tk 8.6 la carga falla y los botones se quedan solo
con texto, sin romper la aplicacion.
"""

import tkinter as tk

ICON_SIZE = 18
ICON_COLOR = "#3b6fd4"
VIEWBOX = 24

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


def load(name, size=ICON_SIZE, color=ICON_COLOR):
  """Devuelve un PhotoImage con el icono, o None si Tk no soporta SVG."""
  key = (name, size, color)
  if key in _cache:
    return _cache[key]

  body = _PATHS.get(name)
  if body is None:
    return None

  svg = _TEMPLATE.format(box=VIEWBOX, color=color, body=body)
  try:
    image = tk.PhotoImage(data=svg, format=f"svg -scale {size / VIEWBOX}")
  except tk.TclError:
    return None

  _cache[key] = image
  return image


def button_options(name, text):
  """Opciones para un ttk.Button con icono, degradando a solo texto."""
  options = {"text": text}
  icon = load(name)
  if icon is not None:
    options.update(image=icon, compound=tk.LEFT, padding=(8, 4))
  return options
