from django.urls import path

from affiliations_service import views
from affiliations_service.api.v1 import api

app_name = "as"

urlpatterns = [
    path("", views.index, name="index"),
    path("affiliations/new/", views.affiliation_create, name="affiliation-create"),
    path(
        "affiliations/<uuid:pk>/edit/",
        views.affiliation_edit,
        name="affiliation-edit",
    ),
    path(
        "affiliations/<uuid:pk>/delete/",
        views.affiliation_delete,
        name="affiliation-delete",
    ),
    path(
        "affiliations/<uuid:pk>/",
        views.affiliation_detail,
        name="affiliation",
    ),
    path("api/v1/", api.urls),
]
