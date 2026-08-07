from .controllers import MainController
from .models import ImageModel
from .models.preferences import PreferencesRepository
from .views import MainView


def create_app():
  # Una sola base para todo: rotaciones por imagen y ajustes de la app.
  preferences = PreferencesRepository()
  return MainController(ImageModel(preferences), MainView(), preferences)
