from django.urls import path

from clinvar_submission_service import views
from clinvar_submission_service.api import api

app_name = "css"

urlpatterns = [
    path("", views.index, name="index"),
    path("submissions/<slug:slug>/", views.submission_detail, name="detail"),
    path("submissions/<slug:slug>/resend/", views.resend, name="resend"),
    path("api/v1/", api.urls),
]
