class MainController:
  """Conecta la vista con el modelo."""

  def __init__(self, model, view):
    self.model = model
    self.view = view

    self.view.bind_open_image(self.on_open_image)
    self.view.bind_select_file(self.on_select_file)
    self.view.bind_rotate(self.on_rotate_left, self.on_rotate_right)
    self.model.subscribe(self.on_model_changed)

  def run(self):
    self.view.mainloop()

  def on_open_image(self):
    path = self.view.ask_image_path()
    if path is None:
      return

    self._load(path)

  def on_select_file(self, index):
    files = self.model.files
    if index == self.model.index or not 0 <= index < len(files):
      return
    self._load(files[index])

  def on_rotate_left(self):
    self.model.rotate(-90)

  def on_rotate_right(self):
    self.model.rotate(90)

  def on_model_changed(self, model):
    if not model.has_image:
      self.view.clear_image()
      return

    self.view.show_file_list([path.name for path in model.files], model.index)
    self.view.show_metadata(model.metadata)
    self.view.show_image(model.image, model.path.name, model.rotation)

  def _load(self, path):
    try:
      self.model.load(path)
    except (OSError, ValueError) as error:
      self.view.show_error(f"No se pudo abrir la imagen:\n{error}")
      # La lista quedo marcando el archivo fallido: la devolvemos al actual.
      self.view.show_file_list([item.name for item in self.model.files], self.model.index)
