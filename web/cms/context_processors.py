from django.conf import settings

from .models import Page


def footer_pages(request):
    """Live pages flagged for the footer, in admin-configured order. Fetched
    lazily so pages that never render the footer links don't pay for the query."""
    from django.utils.functional import SimpleLazyObject

    return {
        "articles_enabled": settings.CMS_ARTICLES_ENABLED,
        "footer_pages": SimpleLazyObject(
            lambda: list(
                Page.objects.live()
                .filter(show_in_footer=True)
                .order_by("footer_order", "title")
                .only("title", "slug")
            )
        )
    }
