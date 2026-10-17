from django.urls import path

from clinvar_submission_service import views

app_name = "css"

urlpatterns = [
    path("", views.index, name="index"),
]
