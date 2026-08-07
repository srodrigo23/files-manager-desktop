from .controllers import MainController
from .models import ImageModel
from .models.preferences import WINDOW_GEOMETRY, PreferencesRepository
from .views import MainView


def create_app():
  # Una sola base para todo: rotaciones por imagen, ajustes y estado de sesion.
  preferences = PreferencesRepository()
  view = MainView(geometry=preferences.get_value(WINDOW_GEOMETRY))
  return MainController(ImageModel(preferences), view, preferences)
