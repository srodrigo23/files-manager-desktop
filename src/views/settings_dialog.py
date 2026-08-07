"""Ventana modal de configuracion."""

import tkinter as tk
from tkinter import ttk

from .widgets import IconButton

DIALOG_WIDTH = 460

# (clave, etiqueta, explicacion). La explicacion importa: un ajuste que apaga
# una confirmacion deberia decir que se pierde a cambio.
OPTIONS = (
  (
    "confirm_delete",
    "Preguntar antes de eliminar",
    "Si lo desactivas, la imagen se manda a la papelera al instante.\n"
    "Seguira siendo recuperable desde la papelera del sistema.",
  ),
)


class SettingsDialog(tk.Toplevel):
  """Aplica cada cambio al momento: no hay Aceptar ni Cancelar."""

  def __init__(self, parent, values, on_change):
    super().__init__(parent)
    self._on_change = on_change
    self._variables = {}

    self.title("Configuración")
    self.resizable(False, False)
    self.transient(parent)

    self._build_options(values)
    self._center_over(parent)

    self.bind("<Escape>", lambda _event: self.destroy())
    self.grab_set()
    self.focus_set()

  def _build_options(self, values):
    container = ttk.Frame(self, padding=(20, 18))
    container.pack(fill=tk.BOTH, expand=True)

    for index, (key, label, description) in enumerate(OPTIONS):
      variable = tk.BooleanVar(value=values.get(key, True))
      self._variables[key] = variable

      check = ttk.Checkbutton(
        container,
        text=label,
        variable=variable,
        command=lambda k=key: self._notify(k),
      )
      check.grid(row=index * 2, column=0, sticky=tk.W)

      hint = ttk.Label(container, text=description, foreground="#6b6b6b", justify=tk.LEFT)
      hint.grid(row=index * 2 + 1, column=0, sticky=tk.W, padx=(22, 0), pady=(2, 14))

    IconButton(container, "Cerrar", command=self.destroy).grid(
      row=len(OPTIONS) * 2, column=0, sticky=tk.E, pady=(6, 0)
    )

  def _notify(self, key):
    self._on_change(key, self._variables[key].get())

  def _center_over(self, parent):
    self.update_idletasks()
    width = self.winfo_reqwidth()
    height = self.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
    self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
