from ..models.preferences import CONFIRM_DELETE, DEFAULT_SETTINGS


class MainController:
  """Conecta la vista con el modelo."""

  def __init__(self, model, view, preferences=None):
    self.model = model
    self.view = view
    self._preferences = preferences
    self._settings = self._load_settings()
    # Las acciones por teclado (rotar, eliminar) arrancan dormidas: se
    # habilitan con Enter para que una flecha suelta no altere la imagen.
    self._actions_active = False
    self._active_path = None

    self.view.bind_open_image(self.on_open_image)
    self.view.bind_select_file(self.on_select_file)
    self.view.bind_rotate(self.on_rotate_left, self.on_rotate_right)
    self.view.bind_delete(self.on_delete_image)
    self.view.bind_rename(self.on_rename_image)
    self.view.bind_settings(self.on_open_settings)
    self.view.bind_navigation(self.on_previous_image, self.on_next_image)
    self.view.bind_actions(
      self.on_activate_actions,
      self.on_cancel_actions,
      self.on_key_rotate_left,
      self.on_key_rotate_right,
      # Eliminar no pasa por el modo: ya tiene su propia confirmacion.
      self.on_delete_image,
    )
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

  def on_previous_image(self):
    self._step(-1)

  def on_next_image(self):
    self._step(1)

  def _step(self, delta):
    """Salta a la imagen vecina. Se detiene en los extremos, no da la vuelta."""
    files = self.model.files
    index = self.model.index
    if index < 0:
      return

    target = index + delta
    if 0 <= target < len(files):
      self._load(files[target])

  def on_activate_actions(self):
    """Enter: habilita rotar y eliminar desde el teclado."""
    if self.model.has_image:
      self._set_actions_active(True)

  def on_cancel_actions(self):
    self._set_actions_active(False)

  # Los botones siempre funcionan; el modo solo condiciona las teclas.

  def on_key_rotate_left(self):
    if self._actions_active:
      self.on_rotate_left()

  def on_key_rotate_right(self):
    if self._actions_active:
      self.on_rotate_right()

  def on_rotate_left(self):
    self.model.rotate(-90)

  def on_rotate_right(self):
    self.model.rotate(90)

  def _set_actions_active(self, active):
    self._actions_active = active
    self.view.set_actions_active(active)

  def on_open_settings(self):
    self.view.show_settings(dict(self._settings), self.on_setting_changed)

  def on_setting_changed(self, key, value):
    self._settings[key] = value
    if self._preferences:
      self._preferences.set_flag(key, value)

  def _load_settings(self):
    if self._preferences is None:
      return dict(DEFAULT_SETTINGS)
    return {
      key: self._preferences.get_flag(key, default)
      for key, default in DEFAULT_SETTINGS.items()
    }

  def on_rename_image(self):
    if not self.model.has_image:
      return

    path = self.model.path
    new_name = self.view.ask_new_name(path.stem, path.suffix)
    if new_name is None:
      return

    # Renombrar cambia la ruta, y eso apagaria el modo como si fuera otra
    # imagen. Es la misma: conservamos el estado que tenia.
    was_active = self._actions_active
    try:
      self.model.rename(new_name)
    except (ValueError, FileExistsError, OSError) as error:
      self.view.show_error(f"No se pudo renombrar:\n{error}")
      return

    if was_active:
      self._set_actions_active(True)

  def on_delete_image(self):
    if not self.model.has_image:
      return

    name = self.model.path.name
    if self._settings[CONFIRM_DELETE] and not self.view.confirm_delete(name):
      return

    try:
      following = self.model.send_to_trash()
    except OSError as error:
      self.view.show_error(f"No se pudo mover «{name}» a la papelera:\n{error}")
      return

    # Si no queda nada que abrir, o lo que sigue no se puede leer, dejamos el
    # visor limpio en vez de seguir mostrando un archivo que ya no existe.
    if following is None or not self._load(following):
      self.model.clear()

  def on_model_changed(self, model):
    if not model.has_image:
      # Sin imagen no hay nada sobre lo que actuar: el modo se apaga solo.
      self._set_actions_active(False)
      self._active_path = None
      self.view.clear_image()
      return

    # Cada imagen exige su propio Enter. Rotar no cambia la ruta, asi que el
    # modo sobrevive a sus propias acciones, solo no al cambio de imagen.
    if model.path != self._active_path:
      self._active_path = model.path
      self._set_actions_active(False)

    self.view.show_file_list([path.name for path in model.files], model.index)
    self.view.show_metadata(model.metadata)
    self.view.show_image(model.image, model.path.name, model.rotation)

  def _load(self, path):
    """Carga la imagen. Devuelve False si no se pudo leer."""
    try:
      self.model.load(path)
      return True
    except (OSError, ValueError) as error:
      self.view.show_error(f"No se pudo abrir la imagen:\n{error}")
      # La lista quedo marcando el archivo fallido: la devolvemos al actual.
      self.view.show_file_list([item.name for item in self.model.files], self.model.index)
      return False
