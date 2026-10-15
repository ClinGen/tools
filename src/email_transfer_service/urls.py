from django.urls import path

from email_transfer_service import views

app_name = "ets"

urlpatterns = [
    path("", views.index, name="index"),
    path("transfers/", views.transfer_list, name="list"),
    path("transfers/<slug:slug>/", views.transfer_detail, name="detail"),
]
