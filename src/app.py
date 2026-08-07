from .controllers import MainController
from .models import ImageModel
from .views import MainView


def create_app():
  return MainController(ImageModel(), MainView())
