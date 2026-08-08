"""Preferencias por imagen, guardadas en un SQLite propio de la app.

Persistir aqui y no en el archivo tiene una consecuencia buscada: la rotacion
sobrevive entre sesiones sin que la imagen original cambie ni un byte.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

APP_FOLDER = "PicsViewer"
DATABASE_FILENAME = "preferences.db"

# Ajustes que el usuario cambia desde la modal, con su valor por defecto.
CONFIRM_DELETE = "confirm_delete"
SHOW_FILES = "show_files"
SHOW_DETAILS = "show_details"
CYCLE_NAVIGATION = "cycle_navigation"
DEFAULT_SETTINGS = {
  CONFIRM_DELETE: True,
  SHOW_FILES: True,
  SHOW_DETAILS: True,
  CYCLE_NAVIGATION: True,
}

# Estado de sesion: no se edita a mano, lo escribe la app al usarse.
LAST_IMAGE = "last_image"
WINDOW_GEOMETRY = "window_geometry"
FILES_WIDTH = "files_width"
DETAILS_WIDTH = "details_width"


class Base(DeclarativeBase):
  pass


class ImagePreference(Base):
  """Lo que recordamos de una imagen concreta, identificada por su ruta."""

  __tablename__ = "image_preferences"

  path: Mapped[str] = mapped_column(String, primary_key=True)
  rotation: Mapped[int] = mapped_column(Integer, default=0)
  updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: _now())


class AppSetting(Base):
  """Ajustes globales de la app, en formato clave/valor."""

  __tablename__ = "app_settings"

  key: Mapped[str] = mapped_column(String, primary_key=True)
  value: Mapped[str] = mapped_column(String)


class PreferencesRepository:
  """Acceso a la base. Si algo falla, degrada a 'sin preferencias guardadas'.

  Un visor de imagenes no deberia caerse porque su base auxiliar no se pueda
  escribir, asi que los errores de SQLAlchemy se tragan a proposito.
  """

  def __init__(self, database_path=None):
    self._new_session = None
    try:
      if database_path is None:
        database_path = default_database_path()
        database_path.parent.mkdir(parents=True, exist_ok=True)

      url = "sqlite://" if database_path == ":memory:" else f"sqlite:///{database_path}"
      engine = create_engine(url)
      Base.metadata.create_all(engine)
      self._new_session = sessionmaker(engine)
    except (SQLAlchemyError, OSError):
      # Disco lleno, carpeta de solo lectura, permisos... la app arranca igual
      # y simplemente no recuerda rotaciones.
      pass

  @property
  def available(self):
    return self._new_session is not None

  def rotation_for(self, path):
    if not self.available:
      return 0
    try:
      with self._new_session() as session:
        stored = session.get(ImagePreference, str(path))
        return stored.rotation if stored else 0
    except SQLAlchemyError:
      return 0

  def save_rotation(self, path, rotation):
    if not self.available:
      return
    try:
      with self._new_session() as session:
        key = str(path)
        stored = session.get(ImagePreference, key)

        if rotation == 0:
          # Sin rotacion no hay nada que recordar: no dejamos filas muertas.
          if stored:
            session.delete(stored)
        elif stored:
          stored.rotation = rotation
          stored.updated_at = _now()
        else:
          session.add(ImagePreference(path=key, rotation=rotation, updated_at=_now()))

        session.commit()
    except SQLAlchemyError:
      pass

  def forget(self, path):
    """Olvida una imagen que ya no existe, para no acumular filas huerfanas."""
    self.save_rotation(path, 0)

  # --- Ajustes de la app ---

  def get_value(self, key, default=None):
    if not self.available:
      return default
    try:
      with self._new_session() as session:
        stored = session.get(AppSetting, key)
        return stored.value if stored else default
    except SQLAlchemyError:
      return default

  def set_value(self, key, value):
    if not self.available:
      return
    try:
      with self._new_session() as session:
        stored = session.get(AppSetting, key)
        if stored:
          stored.value = value
        else:
          session.add(AppSetting(key=key, value=value))
        session.commit()
    except SQLAlchemyError:
      pass

  def get_flag(self, key, default):
    stored = self.get_value(key)
    return default if stored is None else stored == "1"

  def set_flag(self, key, value):
    self.set_value(key, "1" if value else "0")


def default_database_path():
  """Carpeta de datos de la aplicacion segun el sistema."""
  home = Path.home()
  if sys.platform == "darwin":
    base = home / "Library" / "Application Support"
  elif sys.platform == "win32":
    base = Path(os.environ.get("APPDATA", home))
  else:
    base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
  return base / APP_FOLDER / DATABASE_FILENAME


def _now():
  return datetime.now(timezone.utc)
