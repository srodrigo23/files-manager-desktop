import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from ..models.image_model import SUPPORTED_EXTENSIONS
from . import icons
from .settings_dialog import SettingsDialog
from .widgets import IconButton

WINDOW_TITLE = "Pics Viewer"
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 600
EMPTY_MESSAGE = "No hay ninguna imagen abierta"
CANVAS_BACKGROUND = "#1e1e1e"
EMPTY_TEXT_COLOR = "#8a8a8a"
CANVAS_PADDING = 12
SIDEBAR_WIDTH = 240
METADATA_WIDTH = 320
ACTION_ICON_TINT = "#ffffff"
DANGER_COLORS = ("#c5453c", "#d65a50", "#a3332c")
NEUTRAL_COLORS = ("#6b7280", "#7d8592", "#565c66")
HINT_INACTIVE = "↑ ↓ cambiar imagen    ·    supr eliminar    ·    Enter activa la rotación"
HINT_ACTIVE = "← → rotar    ·    supr eliminar    ·    Esc salir"
# Espera antes de re-escalar mientras el usuario arrastra el borde de la ventana.
RESIZE_DELAY_MS = 60


class MainView(tk.Tk):
  """Ventana principal. Solo dibuja: la logica vive en el controlador."""

  def __init__(self):
    super().__init__()

    self.title(WINDOW_TITLE)
    self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    self.minsize(480, 320)

    self._source_image = None
    self._image_name = None
    self._photo = None  # referencia viva: tkinter no retiene la imagen por si solo
    self._canvas_size = (0, 0)
    self._resize_job = None
    self._file_names = []
    self._file_position = None
    self._rotation = 0
    self._syncing_list = False
    self._sash_placed = False
    self._settings_dialog = None

    self._build_widgets()
    self._center_on_screen()
    # Arrancamos con la lista lista para recibir teclas, sin pedir un clic.
    self.focus_file_list()

  def _build_widgets(self):
    toolbar = ttk.Frame(self, padding=(12, 10))
    toolbar.pack(side=tk.TOP, fill=tk.X)

    self.open_button = IconButton(toolbar, "Abrir imagen", icon=icons.load("img.png"))
    self.open_button.pack(side=tk.LEFT)

    self.settings_button = IconButton(
      toolbar,
      "Configuración",
      icon=icons.load("setting.png", tint=ACTION_ICON_TINT),
      colors=NEUTRAL_COLORS,
    )
    self.settings_button.pack(side=tk.RIGHT)

    self.status = ttk.Label(self, text="Listo", relief=tk.SUNKEN, anchor=tk.W, padding=(8, 4))
    self.status.pack(side=tk.BOTTOM, fill=tk.X)

    self._build_actions()

    # El divisor deja al usuario ajustar cuanto espacio ocupa la lista.
    self.body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
    self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    self.body.add(self._build_sidebar(self.body), weight=0)

    self.canvas = tk.Canvas(self.body, background=CANVAS_BACKGROUND, highlightthickness=0)
    self.canvas.bind("<Configure>", self._on_canvas_resize)
    self.body.add(self.canvas, weight=1)

    self.body.add(self._build_metadata(self.body), weight=0)
    self.body.bind("<Configure>", self._on_body_configure)

  def _on_body_configure(self, event):
    # Los sash solo admiten una posicion cuando el panel ya tiene ancho real.
    if self._sash_placed or event.width <= 1:
      return
    self._sash_placed = True
    # De derecha a izquierda: mover el de la izquierda primero empuja al otro.
    self.body.sashpos(1, event.width - METADATA_WIDTH)
    self.body.sashpos(0, SIDEBAR_WIDTH)

  def _build_actions(self):
    """Barra inferior de acciones sobre la imagen que se esta viendo."""
    actions = ttk.Frame(self, padding=(12, 10))
    actions.pack(side=tk.BOTTOM, fill=tk.X)
    ttk.Separator(self, orient=tk.HORIZONTAL).pack(side=tk.BOTTOM, fill=tk.X)

    # Los iconos vienen en negro: los tenimos de blanco para que se lean
    # sobre el azul del boton.
    self.rotate_left_button = IconButton(
      actions, "Rotar izquierda", icon=icons.load("rotate-left.png", tint=ACTION_ICON_TINT)
    )
    self.rotate_left_button.pack(side=tk.LEFT)

    self.rotate_right_button = IconButton(
      actions, "Rotar derecha", icon=icons.load("rotate-right.png", tint=ACTION_ICON_TINT)
    )
    self.rotate_right_button.pack(side=tk.LEFT, padx=(8, 0))

    self.rename_button = IconButton(
      actions, "Renombrar", icon=icons.load("edit-text.png", tint=ACTION_ICON_TINT)
    )
    self.rename_button.pack(side=tk.LEFT, padx=(8, 0))

    # Separado del resto y en rojo: es la unica accion destructiva.
    self.delete_button = IconButton(
      actions,
      "Eliminar",
      icon=icons.load("delete.png", tint=ACTION_ICON_TINT),
      colors=DANGER_COLORS,
    )
    self.delete_button.pack(side=tk.RIGHT)

    # Un modo sin indicador es un modo invisible: el texto dice que teclas
    # estan vivas en cada momento.
    self.actions_hint = ttk.Label(actions, text=HINT_INACTIVE, padding=(12, 0))
    self.actions_hint.pack(side=tk.LEFT)

  def _build_sidebar(self, parent):
    sidebar = ttk.Frame(parent, width=SIDEBAR_WIDTH, padding=(8, 0, 0, 8))

    self.files_header = ttk.Label(sidebar, text="Carpeta", padding=(2, 6))
    self.files_header.pack(side=tk.TOP, fill=tk.X)

    scrollbar = ttk.Scrollbar(sidebar, orient=tk.VERTICAL)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    self.files_list = tk.Listbox(
      sidebar,
      activestyle="none",
      borderwidth=0,
      highlightthickness=0,
      exportselection=False,
      yscrollcommand=scrollbar.set,
    )
    self.files_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.configure(command=self.files_list.yview)

    return sidebar

  def _build_metadata(self, parent):
    panel = ttk.Frame(parent, width=METADATA_WIDTH, padding=(0, 0, 8, 8))

    ttk.Label(panel, text="Detalles", padding=(2, 6)).pack(side=tk.TOP, fill=tk.X)

    scrollbar = ttk.Scrollbar(panel, orient=tk.VERTICAL)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Un arbol de dos columnas agrupa los datos por seccion sin widgets extra.
    self.metadata_tree = ttk.Treeview(
      panel,
      columns=("valor",),
      show="tree",
      selectmode="browse",
      yscrollcommand=scrollbar.set,
    )
    # Sangria chica: los nombres de campo entran sin cortarse en 320 px.
    ttk.Style().configure("Metadata.Treeview", indent=10)
    self.metadata_tree.configure(style="Metadata.Treeview")
    self.metadata_tree.column("#0", width=115, minwidth=90, stretch=False)
    self.metadata_tree.column("valor", width=175, minwidth=80, stretch=True)
    self.metadata_tree.tag_configure("seccion", font=_section_font())
    self.metadata_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.configure(command=self.metadata_tree.yview)

    return panel

  def _center_on_screen(self):
    """Coloca la ventana en el centro de la pantalla."""
    self.update_idletasks()

    width = self.winfo_width() or WINDOW_WIDTH
    height = self.winfo_height() or WINDOW_HEIGHT
    x = (self.winfo_screenwidth() - width) // 2
    y = (self.winfo_screenheight() - height) // 2

    self.geometry(f"{width}x{height}+{x}+{y}")

  # --- Renderizado ---

  def _on_canvas_resize(self, event):
    if (event.width, event.height) == self._canvas_size:
      return

    self._canvas_size = (event.width, event.height)

    # Agrupamos los eventos de resize para no re-escalar en cada pixel.
    if self._resize_job is not None:
      self.after_cancel(self._resize_job)
    self._resize_job = self.after(RESIZE_DELAY_MS, self._render)

  def _render(self):
    self._resize_job = None
    self.canvas.delete("all")

    width, height = self._canvas_size
    if width <= 1 or height <= 1:
      return

    if self._source_image is None:
      self.canvas.create_text(
        width // 2, height // 2, text=EMPTY_MESSAGE, fill=EMPTY_TEXT_COLOR
      )
      return

    scaled, zoom = self._fit(self._source_image, width, height)
    self._photo = ImageTk.PhotoImage(scaled)
    self.canvas.create_image(width // 2, height // 2, image=self._photo)
    self._update_status(zoom)

  def _fit(self, image, available_width, available_height):
    """Devuelve la imagen ajustada al canvas y el factor de escala aplicado."""
    max_width = max(available_width - 2 * CANVAS_PADDING, 1)
    max_height = max(available_height - 2 * CANVAS_PADDING, 1)
    width, height = image.size

    # Solo reducimos: una imagen pequena se ve a tamano real, no pixelada.
    zoom = min(max_width / width, max_height / height, 1.0)
    if zoom == 1.0:
      return image, zoom

    target = (max(round(width * zoom), 1), max(round(height * zoom), 1))
    return image.resize(target, Image.LANCZOS), zoom

  def _update_status(self, zoom):
    width, height = self._source_image.size
    parts = [self._image_name, f"{width} x {height} px", f"{round(zoom * 100)}%"]
    if self._rotation:
      parts.append(f"rotada {self._rotation}°")
    if self._file_position is not None:
      position, total = self._file_position
      parts.append(f"{position} de {total}")
    self.status.configure(text="  |  ".join(parts))

  # --- API que usa el controlador ---

  def bind_open_image(self, handler):
    self.open_button.configure(command=handler)

  def bind_rotate(self, on_left, on_right):
    self.rotate_left_button.configure(command=on_left)
    self.rotate_right_button.configure(command=on_right)

  def bind_delete(self, handler):
    self.delete_button.configure(command=handler)

  def bind_rename(self, handler):
    self.rename_button.configure(command=handler)

  def bind_settings(self, handler):
    self.settings_button.configure(command=handler)

  def show_settings(self, values, on_change):
    """Abre la modal de ajustes, o trae al frente la que ya estaba abierta."""
    if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
      self._settings_dialog.lift()
      return self._settings_dialog

    self._settings_dialog = SettingsDialog(self, values, on_change)
    return self._settings_dialog

  def ask_new_name(self, current_stem, suffix):
    """Pide el nombre nuevo. Devuelve None si el usuario cancela.

    Solo se edita el nombre: la extension se conserva, porque cambiarla no
    convierte el archivo y romperia como lo reconoce el visor.
    """
    return simpledialog.askstring(
      "Renombrar imagen",
      f"Nuevo nombre (se conserva «{suffix}»):",
      initialvalue=current_stem,
      parent=self,
    )

  def bind_navigation(self, on_previous, on_next):
    """Flechas arriba/abajo para cambiar de imagen desde cualquier parte."""
    self._bind_key("<Up>", on_previous)
    self._bind_key("<Down>", on_next)

  def bind_actions(self, on_activate, on_cancel, on_rotate_left, on_rotate_right, on_delete):
    """Enter habilita las acciones sobre la imagen; Esc vuelve atras."""
    self._bind_key("<Return>", on_activate)
    self._bind_key("<KP_Enter>", on_activate)
    self._bind_key("<Escape>", on_cancel)
    self._bind_key("<Left>", on_rotate_left)
    self._bind_key("<Right>", on_rotate_right)
    # En los teclados Mac la tecla de borrar manda BackSpace; los teclados
    # completos mandan Delete con la de suprimir. Aceptamos las dos.
    self._bind_key("<Delete>", on_delete)
    self._bind_key("<BackSpace>", on_delete)

  def set_actions_active(self, active):
    self.actions_hint.configure(text=HINT_ACTIVE if active else HINT_INACTIVE)

  def focus_file_list(self):
    self.files_list.focus_set()

  def _bind_key(self, sequence, handler):
    def callback(_event):
      # Dentro del arbol de detalles las teclas son suyas: ahi el usuario
      # esta recorriendo filas, no operando sobre la imagen.
      if self.focus_get() is self.metadata_tree:
        return None
      handler()
      return "break"

    # En la ventana: cubre el foco en el canvas o en un boton. En la lista:
    # sus bindings de clase moverian la seleccion o el scroll por su cuenta,
    # asi que los interceptamos para que todo pase por un solo camino.
    self.bind(sequence, callback)
    self.files_list.bind(sequence, callback)

  def confirm_delete(self, name):
    """Pide confirmacion antes de mandar el archivo a la papelera."""
    return messagebox.askyesno(
      "Eliminar imagen",
      f"¿Mover «{name}» a la papelera?",
      detail="Podras recuperarlo desde la papelera del sistema.",
      icon=messagebox.WARNING,
      default=messagebox.NO,
      parent=self,
    )

  def bind_select_file(self, handler):
    """El handler recibe el indice elegido en la lista."""

    def on_select(_event):
      # Ignoramos el evento cuando somos nosotros quienes movemos la seleccion.
      if self._syncing_list:
        return
      selection = self.files_list.curselection()
      if selection:
        handler(selection[0])

    self.files_list.bind("<<ListboxSelect>>", on_select)

  def ask_image_path(self):
    """Abre el dialogo de archivos y devuelve la ruta elegida (o None)."""
    patterns = " ".join(f"*{extension}" for extension in SUPPORTED_EXTENSIONS)
    path = filedialog.askopenfilename(
      parent=self,
      title="Selecciona una imagen",
      filetypes=[("Imagenes", patterns), ("Todos los archivos", "*.*")],
    )
    return path or None

  def show_file_list(self, names, current_index):
    """Muestra los archivos de la carpeta y marca el que se esta viendo."""
    self._syncing_list = True
    try:
      # Solo repoblamos si cambio la carpeta: evita el parpadeo al navegar.
      if names != self._file_names:
        self._file_names = list(names)
        self.files_list.delete(0, tk.END)
        if names:
          self.files_list.insert(tk.END, *names)
          # Carpeta nueva: devolvemos el foco a la lista, que es desde donde
          # se navega. El dialogo de archivos se lo habia llevado.
          self.focus_file_list()

      self.files_list.selection_clear(0, tk.END)
      if 0 <= current_index < len(names):
        self.files_list.selection_set(current_index)
        self.files_list.see(current_index)
        self._file_position = (current_index + 1, len(names))
      else:
        self._file_position = None
    finally:
      self._syncing_list = False

    self.files_header.configure(text=f"Carpeta  ({len(names)})" if names else "Carpeta")

  def show_metadata(self, sections):
    """Vuelca [(titulo, [(campo, valor), ...])] en el panel de detalles."""
    self.metadata_tree.delete(*self.metadata_tree.get_children())

    for title, rows in sections:
      parent = self.metadata_tree.insert("", tk.END, text=title, open=True, tags=("seccion",))
      for label, value in rows:
        self.metadata_tree.insert(parent, tk.END, text=label, values=(value,))

  def show_image(self, image, name, rotation=0):
    # Tkinter no dibuja modos como P o CMYK: normalizamos antes de mostrar.
    if image.mode not in ("RGB", "RGBA", "L"):
      image = image.convert("RGBA")

    self._source_image = image
    self._image_name = name
    self._rotation = rotation
    self.title(f"{name} - {WINDOW_TITLE}")
    self._render()

  def clear_image(self):
    self._source_image = None
    self._image_name = None
    self._photo = None
    self.title(WINDOW_TITLE)
    self.status.configure(text="Listo")
    self.show_file_list([], -1)
    self.show_metadata([])
    self._render()

  def show_error(self, message):
    messagebox.showerror("Pics Viewer", message, parent=self)
    self.status.configure(text=message)


# Tk borra las fuentes que se quedan sin referencias: la guardamos aparte.
_section_font_cache = None


def _section_font():
  global _section_font_cache
  if _section_font_cache is None:
    _section_font_cache = tkfont.nametofont("TkDefaultFont").copy()
    _section_font_cache.configure(weight="bold")
  return _section_font_cache
