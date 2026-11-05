import json

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def clip(value, limit=50):
    """First `limit` characters of the text, then "..." when it was longer."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


@register.simple_tag
def ld_json(data):
    """A JSON-LD <script>. `<` is escaped so editor-supplied text can never
    close the tag early."""
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return format_html('<script type="application/ld+json">{}</script>', mark_safe(payload))


@register.inclusion_tag("cms/_breadcrumbs.html", takes_context=True)
def breadcrumbs(context, crumbs):
    """`crumbs`: [(label, path_or_None), ...]; renders the visible trail and
    the matching schema.org BreadcrumbList."""
    request = context["request"]
    items = [
        {
            "@type": "ListItem",
            "position": i,
            "name": label,
            "item": request.build_absolute_uri(path or request.path),
        }
        for i, (label, path) in enumerate(crumbs, start=1)
    ]
    return {
        "crumbs": crumbs,
        "ld": {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": items,
        },
    }
