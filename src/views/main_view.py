import re
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
MIN_WIDTH = 480
MIN_HEIGHT = 320
EMPTY_MESSAGE = "No hay ninguna imagen abierta"
CANVAS_BACKGROUND = "#1e1e1e"
BORDER_COLOR = "#c3c3c3"
EMPTY_TEXT_COLOR = "#8a8a8a"
CANVAS_PADDING = 12
SIDEBAR_WIDTH = 350
FILE_COLUMNS = ("name", "size", "modified")
# (columna, titulo, ancho, alineacion)
FILE_COLUMN_LAYOUT = (
  ("name", "Nombre", 165, tk.W),
  ("size", "Tamaño", 75, tk.E),
  ("modified", "Modificado", 90, tk.CENTER),
)
SORT_ARROWS = {True: "  ▼", False: "  ▲"}
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

  def __init__(self, geometry=None):
    super().__init__()

    self.title(WINDOW_TITLE)
    self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    self.minsize(MIN_WIDTH, MIN_HEIGHT)
    self._saved_geometry = geometry

    self._source_image = None
    self._image_name = None
    self._photo = None  # referencia viva: tkinter no retiene la imagen por si solo
    self._canvas_size = (0, 0)
    self._resize_job = None
    self._file_names = []
    self._file_position = None
    self._folder_total = None
    self._rotation = 0
    self._syncing_list = False
    self._sash_placed = False
    self._settings_dialog = None
    self._show_files = True
    self._show_details = True
    self._files_width = SIDEBAR_WIDTH
    self._details_width = METADATA_WIDTH

    self._build_widgets()
    # Solo centramos si no habia una posicion guardada que siga siendo valida.
    if not self._restore_geometry(geometry):
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

    # El divisor deja al usuario ajustar cuanto espacio ocupa cada panel.
    self.body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
    self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    self.sidebar = self._build_sidebar(self.body)
    self.canvas = tk.Canvas(self.body, background=CANVAS_BACKGROUND, highlightthickness=0)
    self.canvas.bind("<Configure>", self._on_canvas_resize)
    self.details = self._build_metadata(self.body)

    self._arrange_panes()
    self.body.bind("<Configure>", self._on_body_configure)

  def _arrange_panes(self):
    """Rearma el divisor con los paneles visibles, en su orden natural."""
    for pane in (self.sidebar, self.canvas, self.details):
      if str(pane) in self.body.panes():
        self.body.forget(pane)

    if self._show_files:
      self.body.add(self.sidebar, weight=0)
    self.body.add(self.canvas, weight=1)
    if self._show_details:
      self.body.add(self.details, weight=0)

    self._place_sashes()

  def _place_sashes(self):
    self.update_idletasks()
    total = self.body.winfo_width()
    if total <= 1:
      # Aun sin tamano real: lo hara el <Configure> cuando lo tenga.
      self._sash_placed = False
      return

    # De derecha a izquierda: mover el de la izquierda primero empuja al otro.
    if self._show_details:
      last_sash = len(self.body.panes()) - 2
      self.body.sashpos(last_sash, max(total - self._details_width, 0))
    if self._show_files:
      self.body.sashpos(0, self._files_width)
    self._sash_placed = True

  def _on_body_configure(self, event):
    # Los sash solo admiten una posicion cuando el panel ya tiene ancho real.
    if self._sash_placed or event.width <= 1:
      return
    self._place_sashes()

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

    framed = _bordered(sidebar)
    scrollbar = ttk.Scrollbar(framed, orient=tk.VERTICAL)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    self.files_list = ttk.Treeview(
      framed,
      columns=FILE_COLUMNS,
      show="headings",
      selectmode="browse",
      yscrollcommand=scrollbar.set,
    )
    for column, title, width, anchor in FILE_COLUMN_LAYOUT:
      self.files_list.heading(column, text=title, anchor=tk.W)
      self.files_list.column(
        column, width=width, minwidth=width - 20, anchor=anchor, stretch=column == "name"
      )
    self.files_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.configure(command=self.files_list.yview)

    return sidebar

  def _build_metadata(self, parent):
    panel = ttk.Frame(parent, width=METADATA_WIDTH, padding=(0, 0, 8, 8))

    ttk.Label(panel, text="Detalles", padding=(2, 6)).pack(side=tk.TOP, fill=tk.X)

    framed = _bordered(panel)
    scrollbar = ttk.Scrollbar(framed, orient=tk.VERTICAL)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Un arbol de dos columnas agrupa los datos por seccion sin widgets extra.
    self.metadata_tree = ttk.Treeview(
      framed,
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

  def _restore_geometry(self, spec):
    """Recupera tamano y posicion de la sesion anterior, si siguen sirviendo.

    La pantalla pudo cambiar desde entonces (monitor desconectado, resolucion
    distinta): una ventana fuera de los limites seria inalcanzable.
    """
    if not spec:
      return False

    match = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", spec)
    if not match:
      return False

    width, height, x, y = (int(value) for value in match.groups())
    if width < MIN_WIDTH or height < MIN_HEIGHT:
      return False

    # Exigimos que quede una franja visible por la que agarrar la ventana.
    visible_margin = 100
    if not -width + visible_margin <= x <= self.winfo_screenwidth() - visible_margin:
      return False
    if not 0 <= y <= self.winfo_screenheight() - visible_margin:
      return False

    self.geometry(spec)
    return True

  def current_geometry(self):
    return self.geometry()

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
    if self._folder_total:
      parts.append(f"{self._folder_total} en la carpeta")
    self.status.configure(text="  |  ".join(parts))

  def set_folder_total(self, total):
    """Peso sumado de los archivos que se estan listando."""
    self._folder_total = total

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

  def bind_close(self, handler):
    """Intercepta el cierre para poder guardar estado antes de salir."""
    self.protocol("WM_DELETE_WINDOW", handler)

  def close(self):
    self.destroy()

  def set_panel_widths(self, files_width, details_width):
    self._files_width = files_width or SIDEBAR_WIDTH
    self._details_width = details_width or METADATA_WIDTH
    # Los sash pueden estar ya colocados con los valores por defecto: si no
    # los recolocamos aqui, el ancho recuperado no se veria nunca.
    self._place_sashes()

  def set_panels_visible(self, show_files, show_details):
    if (show_files, show_details) == (self._show_files, self._show_details):
      return
    # Guardamos los anchos actuales antes de rearmar: al ocultar un panel su
    # sash desaparece y con el se iria la medida que el usuario habia elegido.
    self._remember_widths()
    self._show_files = show_files
    self._show_details = show_details
    self._arrange_panes()

  def panel_widths(self):
    self._remember_widths()
    return self._files_width, self._details_width

  def _remember_widths(self):
    total = self.body.winfo_width()
    if total <= 1:
      return
    if self._show_files:
      self._files_width = self.body.sashpos(0)
    if self._show_details:
      self._details_width = total - self.body.sashpos(len(self.body.panes()) - 2)

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
    """El handler recibe el indice elegido en la tabla."""

    def on_select(_event):
      # Ignoramos el evento cuando somos nosotros quienes movemos la seleccion.
      if self._syncing_list:
        return
      selection = self.files_list.selection()
      if selection:
        handler(int(selection[0]))

    self.files_list.bind("<<TreeviewSelect>>", on_select)

  def ask_image_path(self):
    """Abre el dialogo de archivos y devuelve la ruta elegida (o None)."""
    patterns = " ".join(f"*{extension}" for extension in SUPPORTED_EXTENSIONS)
    path = filedialog.askopenfilename(
      parent=self,
      title="Selecciona una imagen",
      filetypes=[("Imagenes", patterns), ("Todos los archivos", "*.*")],
    )
    return path or None

  def show_file_list(self, rows, current_index):
    """Muestra la tabla de archivos y marca el que se esta viendo.

    rows es [(nombre, tamano, modificado), ...] ya formateado.
    """
    self._syncing_list = True
    try:
      # Solo repoblamos si cambio el contenido: evita el parpadeo al navegar.
      if rows != self._file_names:
        self._file_names = list(rows)
        self.files_list.delete(*self.files_list.get_children())
        for position, row in enumerate(rows):
          self.files_list.insert("", tk.END, iid=str(position), values=row)
        if rows:
          # Carpeta nueva: devolvemos el foco a la tabla, que es desde donde
          # se navega. El dialogo de archivos se lo habia llevado.
          self.focus_file_list()

      if 0 <= current_index < len(rows):
        item = str(current_index)
        self.files_list.selection_set(item)
        self.files_list.see(item)
        self._file_position = (current_index + 1, len(rows))
      else:
        self.files_list.selection_remove(self.files_list.selection())
        self._file_position = None
    finally:
      self._syncing_list = False

    self.files_header.configure(text=f"Carpeta  ({len(rows)})" if rows else "Carpeta")

  def bind_sort(self, handler):
    """Clic en una cabecera ordena por esa columna."""
    for column, title, _width, _anchor in FILE_COLUMN_LAYOUT:
      self.files_list.heading(column, command=lambda key=column: handler(key))

  def set_sort_indicator(self, key, descending):
    for column, title, _width, _anchor in FILE_COLUMN_LAYOUT:
      arrow = SORT_ARROWS[descending] if column == key else ""
      self.files_list.heading(column, text=title + arrow)

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
    self._folder_total = None
    self.show_file_list([], -1)
    self.show_metadata([])
    self._render()

  def show_error(self, message):
    messagebox.showerror("Pics Viewer", message, parent=self)
    self.status.configure(text=message)


def _bordered(parent):
  """Contenedor con un borde de 1 px, para despegar el panel del visor.

  Se hace con highlightthickness y no con relief porque en macOS el tema
  nativo ignora el relieve de los frames.
  """
  frame = tk.Frame(
    parent,
    highlightthickness=1,
    highlightbackground=BORDER_COLOR,
    highlightcolor=BORDER_COLOR,
  )
  frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
  return frame


# Tk borra las fuentes que se quedan sin referencias: la guardamos aparte.
_section_font_cache = None


def _section_font():
  global _section_font_cache
  if _section_font_cache is None:
    _section_font_cache = tkfont.nametofont("TkDefaultFont").copy()
    _section_font_cache.configure(weight="bold")
  return _section_font_cache
