from django.urls import path

from auth_ import views

urlpatterns = [
    path("login", views.login_, name="login"),
    path("callback", views.callback, name="callback"),
    path("logout", views.logout_, name="logout"),
]
