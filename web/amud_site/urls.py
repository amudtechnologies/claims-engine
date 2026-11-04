"""URL configuration for amud_site project."""

from cms import views as cms_views
from cms.sitemaps import sitemaps
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from home import views as home_views

urlpatterns = [
    path("management/admin/", admin.site.urls),
    path("management/summernote/", include("django_summernote.urls")),
    path("robots.txt", home_views.robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap_xml"),
    path("", include("home.urls")),
    path("depositos-judiciales/", include("judicial_deposits.urls")),
    # Last: contains the catch-all /<slug>/ route for CMS pages.
    path("", include("cms.urls")),
]

if settings.MEDIA_S3_BUCKET:
    urlpatterns.insert(0, path("media/<path:path>", cms_views.media, name="media"))
elif settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
