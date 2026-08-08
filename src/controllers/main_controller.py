from pathlib import Path

from ..models.image_model import MAX_GRID_ITEMS, SORT_NAME, scan_folder
from ..models.metadata import format_short_date, format_size
from ..models.preferences import (
  CONFIRM_DELETE,
  CYCLE_NAVIGATION,
  DEFAULT_SETTINGS,
  DETAILS_WIDTH,
  FILES_WIDTH,
  LAST_IMAGE,
  SHOW_DETAILS,
  SHOW_FILES,
  WINDOW_GEOMETRY,
)


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
    self._sort_key = SORT_NAME
    self._sort_descending = False
    self._rows_cache = (None, [], 0)
    # Rutas marcadas con la casilla. Se guardan como rutas y no como indices
    # porque reordenar la tabla cambia los indices pero no la seleccion.
    self._checked = set()
    self._anchor = None
    self._base_checked = set()

    self.view.bind_open_image(self.on_open_image)
    self.view.bind_select_file(self.on_select_file)
    self.view.bind_sort(self.on_sort_by)
    self.view.set_sort_indicator(self._sort_key, self._sort_descending)
    self.view.bind_rotate(self.on_rotate_left, self.on_rotate_right)
    self.view.bind_delete(self.on_delete_image)
    self.view.bind_rename(self.on_rename_image)
    self.view.bind_settings(self.on_open_settings)
    self.view.bind_close(self.on_close)
    self.view.bind_navigation(self.on_previous_image, self.on_next_image)
    self.view.bind_check(self.on_toggle_check, self.on_toggle_all_checks)
    self.view.bind_selection_keys(
      self.on_extend_up,
      self.on_extend_down,
      self.on_toggle_current,
      self.on_clear_checks,
      self.on_selection_run_end,
    )
    self.view.bind_actions(
      self.on_activate_actions,
      self.on_cancel_actions,
      self.on_key_rotate_left,
      self.on_key_rotate_right,
      # Eliminar no pasa por el modo: ya tiene su propia confirmacion.
      self.on_delete_image,
    )
    self.model.subscribe(self.on_model_changed)
    self._restore_layout()

  def run(self):
    self.restore_session()
    self.view.mainloop()

  def restore_session(self):
    """Reabre lo ultimo que se estaba viendo, si sigue estando ahi."""
    if self._preferences is None:
      return

    stored = self._preferences.get_value(LAST_IMAGE)
    if not stored:
      return

    last = Path(stored)
    if last.is_file():
      self._load(last, quiet=True)
      return

    # El archivo ya no esta (renombrado, movido, borrado): al menos abrimos
    # su carpeta, que es lo que el usuario estaba mirando.
    remaining = scan_folder(last.parent)
    if remaining:
      self._load(remaining[0], quiet=True)

  def on_close(self):
    if self._preferences:
      self._preferences.set_value(WINDOW_GEOMETRY, self.view.current_geometry())
      files_width, details_width = self.view.panel_widths()
      self._preferences.set_value(FILES_WIDTH, str(files_width))
      self._preferences.set_value(DETAILS_WIDTH, str(details_width))
    self.view.close()

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

  def on_sort_by(self, key):
    """Clic en cabecera: mismo criterio invierte, criterio nuevo empieza asc."""
    if key == self._sort_key:
      self._sort_descending = not self._sort_descending
    else:
      self._sort_key = key
      self._sort_descending = False

    self.view.set_sort_indicator(self._sort_key, self._sort_descending)
    self.model.set_sort(self._sort_key, self._sort_descending)

  def _folder_summary(self):
    """(filas de la tabla, peso total) con una sola pasada de stats.

    Cada archivo cuesta un stat y esto se llama en cada cambio de imagen: sin
    cache una carpeta grande pagaria el recorrido entero al navegar.
    """
    files = tuple(self.model.files)
    if self._rows_cache[0] != files:
      rows = []
      total = 0
      for path in files:
        stat = _safe_stat(path)
        if stat is None:
          # Archivo desaparecido entre el escaneo y ahora: no suma al total.
          rows.append((path.name, "—", "—"))
          continue
        total += stat.st_size
        rows.append((path.name, format_size(stat.st_size), format_short_date(stat.st_mtime)))
      self._rows_cache = (files, rows, total)

    _files, rows, total = self._rows_cache
    return rows, (format_size(total) if rows else None)

  # --- Seleccion multiple ---

  def on_toggle_check(self, index):
    files = self.model.files
    if not 0 <= index < len(files):
      return
    path = files[index]
    self._checked.symmetric_difference_update({path})
    # Marcar a mano abre un tramo nuevo desde aqui.
    self._start_selection_run(index)
    self._refresh_selection()

  def on_toggle_current(self):
    self.on_toggle_check(self.model.index)

  def on_toggle_all_checks(self):
    files = self.model.files
    # Si ya estaban todas, el mismo clic deselecciona: es el comportamiento
    # esperado de una casilla de cabecera.
    self._checked = set() if self._checked >= set(files) and files else set(files)
    self._start_selection_run(self.model.index)
    self._refresh_selection()

  def on_selection_run_end(self):
    """Soltar Shift cierra el tramo: el proximo arranca un grupo nuevo."""
    self._anchor = None

  def on_clear_checks(self):
    self._checked = set()
    self._anchor = None
    self._base_checked = set()
    self._refresh_selection()

  def on_extend_up(self):
    self._extend(-1)

  def on_extend_down(self):
    self._extend(1)

  def _extend(self, delta):
    """Shift+flecha: invierte el marcado del tramo entre el ancla y el cursor.

    Recalcular el tramo entero contra el estado que habia al empezar, en vez
    de ir sumando, da las dos cosas: cambiar de sentido deshace lo recien
    hecho, y volver a recorrer un tramo ya marcado lo desmarca.
    """
    files = self.model.files
    index = self.model.index
    if index < 0:
      return

    if self._anchor is None:
      self._start_selection_run(index)

    target = index + delta
    if not 0 <= target < len(files):
      return

    low, high = sorted((self._anchor, target))
    # Diferencia simetrica, no union: pasar por encima de algo ya marcado lo
    # desmarca, como en Total Commander. Lo de fuera del tramo no se toca.
    self._checked = set(self._base_checked) ^ set(files[low : high + 1])
    # Mover el cursor recarga la imagen, y eso redibuja tabla y grilla.
    self._load(files[target])

  def _start_selection_run(self, index):
    self._anchor = index
    self._base_checked = set(self._checked)

  def _refresh_selection(self):
    """Sincroniza casillas y visor con el conjunto marcado."""
    files = self.model.files
    checked_indexes = {
      position for position, path in enumerate(files) if path in self._checked
    }
    self.view.set_checked(checked_indexes, bool(files) and len(checked_indexes) == len(files))

    ordered = [path for path in files if path in self._checked]
    if ordered:
      self.view.show_grid(self.model.thumbnails(ordered[:MAX_GRID_ITEMS]), len(ordered))
    else:
      # Sin marcadas volvemos al visor de una sola imagen.
      self.view.show_grid([], 0)
      if self.model.has_image:
        self.view.show_image(self.model.image, self.model.path.name, self.model.rotation)

  def on_previous_image(self):
    self._step(-1)

  def on_next_image(self):
    self._step(1)

  def _step(self, delta):
    """Salta a la imagen vecina, dando la vuelta si el ajuste lo permite."""
    files = self.model.files
    index = self.model.index
    if index < 0:
      return

    target = index + delta
    if self._settings[CYCLE_NAVIGATION]:
      target %= len(files)
    elif not 0 <= target < len(files):
      return

    # Navegar sin Shift cierra el tramo: el proximo Shift arranca de cero.
    self._anchor = None
    self._base_checked = set()

    # Con una sola imagen la vuelta cae en si misma: no vale releerla.
    if target != index:
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
    if key in (SHOW_FILES, SHOW_DETAILS):
      self._apply_panels()

  def _restore_layout(self):
    if self._preferences:
      self.view.set_panel_widths(
        _as_int(self._preferences.get_value(FILES_WIDTH)),
        _as_int(self._preferences.get_value(DETAILS_WIDTH)),
      )
    self._apply_panels()

  def _apply_panels(self):
    self.view.set_panels_visible(self._settings[SHOW_FILES], self._settings[SHOW_DETAILS])

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

    # La ruta cambio: la sesion debe recordar el nombre nuevo.
    self._remember_current()
    if was_active:
      self._set_actions_active(True)

  def on_delete_image(self):
    """Elimina las marcadas; si no hay ninguna, la que se esta viendo."""
    targets = [path for path in self.model.files if path in self._checked]
    if not targets:
      targets = [self.model.path] if self.model.has_image else []
    if not targets:
      return

    if self._settings[CONFIRM_DELETE] and not self.view.confirm_delete(
      [path.name for path in targets]
    ):
      return

    following, failed = self.model.send_to_trash(targets)
    self._checked.difference_update(targets)
    self._anchor = None
    self._base_checked = set()

    if failed:
      self.view.show_error("No se pudieron mover a la papelera:\n" + "\n".join(failed))

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

    rows, total = self._folder_summary()
    self.view.show_file_list(rows, model.index)
    self.view.set_folder_total(total)
    self.view.show_metadata(model.metadata)
    self.view.show_image(model.image, model.path.name, model.rotation)
    # Repoblar la tabla borra las casillas y el visor volvio a la imagen sola:
    # esto devuelve ambos al estado que corresponde a la seleccion actual.
    self._refresh_selection()

  def _load(self, path, quiet=False):
    """Carga la imagen. Devuelve False si no se pudo leer.

    quiet evita el dialogo de error al restaurar la sesion: que la imagen de
    la vez pasada ya no sirva no es motivo para recibir al usuario con un aviso.
    """
    try:
      self.model.load(path)
      self._remember_current()
      return True
    except (OSError, ValueError) as error:
      if not quiet:
        self.view.show_error(f"No se pudo abrir la imagen:\n{error}")
        # La lista quedo marcando el archivo fallido: la devolvemos al actual.
        self.view.show_file_list(self._folder_summary()[0], self.model.index)
      return False

  def _remember_current(self):
    if self._preferences and self.model.path:
      self._preferences.set_value(LAST_IMAGE, str(self.model.path))


def _safe_stat(path):
  try:
    return path.stat()
  except OSError:
    return None


def _as_int(value):
  """Los ajustes se guardan como texto: un valor corrupto no debe romper nada."""
  try:
    return int(value)
  except (TypeError, ValueError):
    return None
