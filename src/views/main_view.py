import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ..models.image_model import SUPPORTED_EXTENSIONS

WINDOW_TITLE = "Pics Viewer"
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 600
EMPTY_MESSAGE = "No hay ninguna imagen abierta"
CANVAS_BACKGROUND = "#1e1e1e"
EMPTY_TEXT_COLOR = "#8a8a8a"
CANVAS_PADDING = 12
SIDEBAR_WIDTH = 240
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
    self._syncing_list = False
    self._sash_placed = False

    self._build_widgets()
    self._center_on_screen()

  def _build_widgets(self):
    toolbar = ttk.Frame(self, padding=(12, 10))
    toolbar.pack(side=tk.TOP, fill=tk.X)

    self.open_button = ttk.Button(toolbar, text="Abrir imagen")
    self.open_button.pack(side=tk.LEFT)

    self.status = ttk.Label(self, text="Listo", relief=tk.SUNKEN, anchor=tk.W, padding=(8, 4))
    self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # El divisor deja al usuario ajustar cuanto espacio ocupa la lista.
    self.body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
    self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    self.body.add(self._build_sidebar(self.body), weight=0)

    self.canvas = tk.Canvas(self.body, background=CANVAS_BACKGROUND, highlightthickness=0)
    self.canvas.bind("<Configure>", self._on_canvas_resize)
    self.body.add(self.canvas, weight=1)
    self.body.bind("<Configure>", self._on_body_configure)

  def _on_body_configure(self, event):
    # El sash solo admite una posicion cuando el panel ya tiene ancho real.
    if self._sash_placed or event.width <= 1:
      return
    self._sash_placed = True
    self.body.sashpos(0, SIDEBAR_WIDTH)

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
    if self._file_position is not None:
      position, total = self._file_position
      parts.append(f"{position} de {total}")
    self.status.configure(text="  |  ".join(parts))

  # --- API que usa el controlador ---

  def bind_open_image(self, handler):
    self.open_button.configure(command=handler)

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

  def show_image(self, image, name):
    # Tkinter no dibuja modos como P o CMYK: normalizamos antes de mostrar.
    if image.mode not in ("RGB", "RGBA", "L"):
      image = image.convert("RGBA")

    self._source_image = image
    self._image_name = name
    self.title(f"{name} - {WINDOW_TITLE}")
    self._render()

  def clear_image(self):
    self._source_image = None
    self._image_name = None
    self._photo = None
    self.title(WINDOW_TITLE)
    self.status.configure(text="Listo")
    self.show_file_list([], -1)
    self._render()

  def show_error(self, message):
    messagebox.showerror("Pics Viewer", message, parent=self)
    self.status.configure(text=message)
