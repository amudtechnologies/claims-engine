from django.urls import path

from . import views

app_name = "home"

urlpatterns = [
    path("", views.index, name="index"),
    path("radares/", views.radares, name="radares"),
    path("resultados/", views.results, name="results"),
]
