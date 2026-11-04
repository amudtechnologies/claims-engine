from django.core.paginator import Paginator
from django.http import Http404, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .models import Article, Category, Page, Redirect

ARTICLES_PER_PAGE = 9


def _can_preview(request, model) -> bool:
    opts = model._meta
    perm = f"{opts.app_label}.change_{opts.model_name}"
    return request.user.is_staff and request.user.has_perm(perm)


def _get_live_or_redirect(request, model, slug):
    """Live row for `slug`; a staff user with change permission may also see
    drafts (marked noindex in the template). Otherwise a retired slug 301s to
    its replacement, and anything else — draft, unpublished, deleted — is a 404."""
    try:
        obj = model.objects.get(slug=slug)
    except model.DoesNotExist:
        obj = None
    if obj is not None and (obj.is_live or _can_preview(request, model)):
        return obj, None
    if obj is None:
        redirect = Redirect.objects.filter(old_path=request.path).first()
        if redirect:
            return None, HttpResponsePermanentRedirect(redirect.new_path)
    raise Http404


def page_detail(request, slug):
    page, redirect = _get_live_or_redirect(request, Page, slug)
    if redirect:
        return redirect
    return render(
        request,
        "cms/page_detail.html",
        {
            "page": page,
            "page_title": f"{page.seo_title} — Amud Technologies",
            "page_description": page.meta_description,
            "crumbs": [("Inicio", reverse("home:index")), (page.title, None)],
            "is_preview": not page.is_live,
        },
    )


def article_detail(request, slug):
    article, redirect = _get_live_or_redirect(request, Article, slug)
    if redirect:
        return redirect
    categories = [c for c in article.categories.all() if c.is_active]
    related = (
        Article.objects.live()
        .filter(categories__in=categories)
        .exclude(pk=article.pk)
        .distinct()[:3]
        if categories
        else []
    )
    canonical_url = request.build_absolute_uri(article.get_absolute_url())
    article_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.seo_title,
        "description": article.meta_description or article.excerpt[:160],
        "mainEntityOfPage": canonical_url,
        "author": {"@type": "Organization" if not article.author else "Person",
                   "name": article.author_display},
        "publisher": {"@type": "Organization", "name": "Amud Technologies"},
        "datePublished": article.published_at.isoformat() if article.published_at else None,
        "dateModified": article.updated_at.isoformat(),
    }
    if article.featured_image:
        article_ld["image"] = request.build_absolute_uri(article.featured_image.url)
    return render(
        request,
        "cms/article_detail.html",
        {
            "article": article,
            "categories": categories,
            "related_articles": related,
            "canonical_url": canonical_url,
            "article_ld": article_ld,
            "crumbs": [
                ("Inicio", reverse("home:index")),
                ("Guías", reverse("cms:article_list")),
                (article.title, None),
            ],
            "active_nav": "articles",
            "page_title": f"{article.seo_title} — Amud Technologies",
            "page_description": article.meta_description or article.excerpt[:160],
            "is_preview": not article.is_live,
        },
    )


def article_list(request, category_slug=None):
    articles = Article.objects.live().select_related("author").prefetch_related("categories")
    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug, is_active=True)
        articles = articles.filter(categories=category)
    page_obj = Paginator(articles, ARTICLES_PER_PAGE).get_page(request.GET.get("page"))
    if category:
        title = category.meta_title or f"{category.name} — Guías y noticias"
        description = category.meta_description or category.description
    else:
        title = "Guías y noticias sobre depósitos judiciales y acreencias"
        description = (
            "Guías prácticas y novedades sobre depósitos judiciales, acreencias y "
            "derechos económicos en Colombia, publicadas por Amud Technologies."
        )
    crumbs = [("Inicio", reverse("home:index"))]
    if category:
        crumbs += [("Guías", reverse("cms:article_list")), (category.name, None)]
    else:
        crumbs.append(("Guías", None))
    return render(
        request,
        "cms/article_list.html",
        {
            "crumbs": crumbs,
            "page_obj": page_obj,
            "category": category,
            "categories": Category.objects.filter(
                is_active=True, pk__in=Article.objects.live().values("categories")
            ),
            "active_nav": "articles",
            "page_title": f"{title} — Amud Technologies",
            "page_description": description,
        },
    )
