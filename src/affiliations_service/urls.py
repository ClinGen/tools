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
    path(
        "affiliations/<uuid:pk>/members/",
        views.membership_add,
        name="membership-add",
    ),
    path(
        "memberships/<uuid:pk>/end/",
        views.membership_end,
        name="membership-end",
    ),
    path("users/search/", views.user_search, name="user-search"),
    path("users/", views.user_list, name="users"),
    path("users/new/", views.user_create, name="user-create"),
    path("users/<uuid:pk>/edit/", views.user_edit, name="user-edit"),
    path("users/<uuid:pk>/", views.user_detail, name="user"),
    path("cdwgs/", views.cdwg_list, name="cdwgs"),
    path("cdwgs/new/", views.cdwg_create, name="cdwg-create"),
    path("cdwgs/<uuid:pk>/edit/", views.cdwg_edit, name="cdwg-edit"),
    path("api/v1/", api.urls),
]
