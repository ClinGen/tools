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
    path("people/search/", views.person_search, name="person-search"),
    path("people/", views.person_list, name="people"),
    path("people/new/", views.person_create, name="person-create"),
    path("people/<uuid:pk>/edit/", views.person_edit, name="person-edit"),
    path("people/<uuid:pk>/", views.person_detail, name="person"),
    path("cdwgs/", views.cdwg_list, name="cdwgs"),
    path("cdwgs/new/", views.cdwg_create, name="cdwg-create"),
    path("cdwgs/<uuid:pk>/edit/", views.cdwg_edit, name="cdwg-edit"),
    path("api/v1/", api.urls),
]
