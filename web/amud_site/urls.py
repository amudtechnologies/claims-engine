"""URL configuration for amud_site project."""

from django.contrib import admin
from django.urls import include, path
from home import views as home_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("robots.txt", home_views.robots_txt, name="robots_txt"),
    path("sitemap.xml", home_views.sitemap_xml, name="sitemap_xml"),
    path("", include("home.urls")),
    path("depositos-judiciales/", include("judicial_deposits.urls")),
]
