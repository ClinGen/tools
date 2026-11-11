from django.urls import path

from affiliations_service import views

app_name = "as"

urlpatterns = [
    path("", views.index, name="index"),
]
