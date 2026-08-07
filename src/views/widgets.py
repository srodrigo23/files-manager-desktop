"""Widgets propios.

macOS dibuja los botones nativos por su cuenta e ignora background/foreground,
asi que para un boton con color propio hay que dibujarlo a mano.
"""

import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

# El canvas de Tk no tiene antialiasing: dibujamos en grande con Pillow y
# reducimos, que es lo que deja las esquinas suaves en vez de escalonadas.
SUPERSAMPLE = 4

NORMAL = "#3b6fd4"
HOVER = "#4c81e6"
PRESSED = "#2d59ab"


class IconButton(tk.Canvas):
  """Boton con icono, esquinas redondeadas y estados de hover/pressed."""

  def __init__(
    self,
    parent,
    text,
    icon=None,
    command=None,
    colors=(NORMAL, HOVER, PRESSED),
    text_color="#ffffff",
    radius=10,
    height=44,
    padding_x=18,
    gap=10,
    font=("Helvetica", 13),
  ):
    self._command = command
    self._colors = dict(zip(("normal", "hover", "pressed"), colors))
    self._radius = radius
    self._backgrounds = {}
    self._icon = icon  # referencia viva mientras exista el boton
    self._inside = False
    self._pressed = False

    button_font = tkfont.Font(font=font)
    icon_space = icon.width() + gap if icon else 0
    width = padding_x * 2 + icon_space + button_font.measure(text)

    super().__init__(
      parent,
      width=width,
      height=height,
      highlightthickness=0,
      borderwidth=0,
      takefocus=1,
      cursor="hand2",
      background=_parent_background(parent),
    )

    self._size = (width, height)

    # El fondo va primero para que icono y texto queden por encima.
    self._background_id = self.create_image(0, 0, anchor=tk.NW)

    x = padding_x
    if icon:
      self.create_image(x, height // 2, anchor=tk.W, image=icon)
      x += icon.width() + gap
    self.create_text(
      x, height // 2, anchor=tk.W, text=text, fill=text_color, font=button_font
    )

    self._paint("normal")

    self.bind("<Enter>", self._on_enter)
    self.bind("<Leave>", self._on_leave)
    self.bind("<ButtonPress-1>", self._on_press)
    self.bind("<ButtonRelease-1>", self._on_release)
    self.bind("<Return>", self._on_key)
    self.bind("<space>", self._on_key)

  # --- API tipo ttk.Button ---

  def configure(self, cnf=None, **kwargs):
    if "command" in kwargs:
      self._command = kwargs.pop("command")
    if kwargs or cnf:
      return super().configure(cnf, **kwargs)
    return None

  config = configure

  def invoke(self):
    if self._command is not None:
      self._command()

  # --- Estados ---

  def _on_enter(self, _event):
    self._inside = True
    self._paint("pressed" if self._pressed else "hover")

  def _on_leave(self, _event):
    self._inside = False
    self._paint("normal")

  def _on_press(self, _event):
    self._pressed = True
    self.focus_set()
    self._paint("pressed")

  def _on_release(self, _event):
    was_pressed = self._pressed
    self._pressed = False
    self._paint("hover" if self._inside else "normal")
    # Soltar fuera del boton cancela, igual que en un boton nativo.
    if was_pressed and self._inside:
      self.invoke()

  def _on_key(self, _event):
    self.invoke()
    return "break"

  def _paint(self, state):
    self.itemconfigure(self._background_id, image=self._background(state))

  def _background(self, state):
    if state not in self._backgrounds:
      width, height = self._size
      scale = SUPERSAMPLE
      canvas = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
      ImageDraw.Draw(canvas).rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=self._radius * scale,
        fill=self._colors[state],
      )
      shrunk = canvas.resize((width, height), Image.LANCZOS)
      self._backgrounds[state] = ImageTk.PhotoImage(shrunk)
    return self._backgrounds[state]


def _parent_background(parent):
  """Color detras del boton, para que las esquinas redondeadas no se recorten."""
  try:
    return parent.cget("background")
  except tk.TclError:
    # Los contenedores ttk no exponen background: lo sacamos del tema.
    from tkinter import ttk

    return ttk.Style().lookup("TFrame", "background") or "#ececec"
