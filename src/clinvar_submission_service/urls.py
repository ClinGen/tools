from django.urls import path

from clinvar_submission_service import views
from clinvar_submission_service.api import api

app_name = "css"

urlpatterns = [
    path("", views.index, name="index"),
    path("records/", views.records, name="records"),
    path("records/<slug:slug>/", views.record_detail, name="record"),
    path("affiliations/", views.affiliations, name="affiliations"),
    path(
        "affiliations/<int:affiliation_id>/new-batch/",
        views.new_batch,
        name="new_batch",
    ),
    path(
        "affiliations/<int:affiliation_id>/settings/",
        views.affiliation_settings,
        name="affiliation_settings",
    ),
    path("batches/<slug:slug>/", views.batch_detail, name="detail"),
    path("batches/<slug:slug>/resend/", views.resend, name="resend"),
    path("records/<slug:slug>/withdraw/", views.withdraw, name="withdraw"),
    path("api/v1/", api.urls),
]
