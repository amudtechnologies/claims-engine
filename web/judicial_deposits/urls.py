from django.urls import path

from . import views

app_name = "judicial_deposits"

urlpatterns = [
    path("", views.index, name="index"),
]
