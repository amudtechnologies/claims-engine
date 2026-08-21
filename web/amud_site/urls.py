"""URL configuration for amud_site project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("home.urls")),
    path("depositos-judiciales/", include("judicial_deposits.urls")),
]
