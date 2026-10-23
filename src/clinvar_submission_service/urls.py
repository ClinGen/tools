from django.urls import path

from clinvar_submission_service import views
from clinvar_submission_service.api import api

app_name = "css"

urlpatterns = [
    path("", views.index, name="index"),
    path("affiliations/", views.affiliations, name="affiliations"),
    path("batches/<slug:slug>/", views.batch_detail, name="detail"),
    path("batches/<slug:slug>/resend/", views.resend, name="resend"),
    path("api/v1/", api.urls),
]
