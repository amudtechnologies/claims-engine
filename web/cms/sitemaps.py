from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from home import radars

from .models import Article, Category, Page


class StaticSitemap(Sitemap):

    def items(self):
        items = [("home:index", 1.0, "weekly"), ("home:radares", 0.6, "monthly")]
        # Each active radar's landing page comes from its own registration.
        items += [(r.landing_url_name, 0.9, "weekly") for r in radars.all_radars() if r.is_active]
        if settings.CMS_ARTICLES_ENABLED and Article.objects.live().exists():
            items.append(("cms:article_list", 0.7, "daily"))
        return items

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]

    def changefreq(self, item):
        return item[2]


class PageSitemap(Sitemap):
    priority = 0.5

    def items(self):
        return Page.objects.live()

    def lastmod(self, obj):
        return obj.updated_at


class ArticleSitemap(Sitemap):
    priority = 0.7

    def items(self):
        return Article.objects.live()

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    priority = 0.4

    def items(self):
        live = Article.objects.live().values("categories")
        return Category.objects.filter(is_active=True, pk__in=live)


sitemaps = {"static": StaticSitemap, "pages": PageSitemap}
if settings.CMS_ARTICLES_ENABLED:
    sitemaps |= {"articles": ArticleSitemap, "categories": CategorySitemap}
