from django.urls import path

from affiliations_service import views
from affiliations_service.api.v1 import api

app_name = "as"

urlpatterns = [
    path("", views.index, name="index"),
    path("api/v1/", api.urls),
]
