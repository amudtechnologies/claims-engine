from django.conf import settings
from django.urls import path

from . import views

app_name = "cms"

# Included last in the project URLconf: the catch-all <slug>/ page route must
# not shadow any fixed route (see models.RESERVED_SLUGS).
urlpatterns = []
if settings.CMS_ARTICLES_ENABLED:
    urlpatterns += [
        path("guias/", views.article_list, name="article_list"),
        path("guias/categoria/<slug:category_slug>/", views.article_list, name="category"),
        path("guias/<slug:slug>/", views.article_detail, name="article_detail"),
    ]
urlpatterns.append(path("<slug:slug>/", views.page_detail, name="page"))
