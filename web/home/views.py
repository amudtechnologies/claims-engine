from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from . import radars


def robots_txt(request):
    """Excludes the per-query result pages (/resultados/ and each radar's own
    detail page) from crawling — personalized utility pages, also marked
    noindex in their templates, never a page a search result should point to.
    This is both a thin-content and a privacy consideration, since a crawled
    URL could otherwise carry a real document number (see
    docs/seo-strategy.md). The sitemap itself is django.contrib.sitemaps
    (cms/sitemaps.py), wired in urls.py."""
    private_paths = [reverse("home:results")] + [
        reverse(name) for spec in radars.all_radars() for name in spec.private_url_names
    ]
    lines = [
        "User-agent: *",
        *(f"Disallow: {path}" for path in private_paths),
        "Disallow: /management/",
        "",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def index(request):
    context = {
        "active_nav": "home",
        # The home page carries the company concept (money, claims and assets
        # found in public data); each radar landing owns its own product
        # queries, so the two don't compete for the same terms.
        "page_title": "Dinero, acreencias y activos sin reclamar a su nombre — Amud Technologies",
        "page_description": (
            "Monitoreamos y analizamos información pública de fuentes oficiales "
            "en Colombia para identificar dinero y activos sin reclamar."
        ),
        # The "Radares" section (#radares): one card per registered radar.
        # Only active radars are shown — no "En desarrollo" placeholders.
        "radars": [
            (spec, spec.card_stats() if spec.card_stats else [])
            for spec in radars.all_radars()
            if spec.is_active
        ],
    }
    return render(request, "home/index.html", context)


def radares(request):
    """The radar index used to be its own page; it is now the #radares
    section of the home page. Kept as a permanent redirect for old links."""
    return redirect(reverse("home:index") + "#radares", permanent=True)


def results(request):
    raw_document_number = request.GET.get("nit", "").strip()
    if not raw_document_number:
        return redirect("home:index")

    normalized_document_number = "".join(c for c in raw_document_number if c.isdigit())
    context = {
        # A per-query page, not a nav destination: no nav item is active here.
        "active_nav": None,
        "page_title": "Resultados de su consulta — Amud Technologies",
        "page_description": (
            "Resultados de la búsqueda por número de identificación en los "
            "radares activos de Amud Technologies."
        ),
        "raw_document_number": raw_document_number,
        "normalized_document_number": normalized_document_number,
        "searched_at": timezone.localdate(),
        # Below this many digits the input isn't a NIT or cédula-shaped number
        # at all — worth telling the user to check what they typed, distinct
        # from a well-formed document number that genuinely has no match in
        # the radars processed so far.
        "document_number_looks_invalid": len(normalized_document_number) < 5,
    }

    available = [r for r in radars.all_radars() if r.is_active and r.is_available()]
    if not available:
        context["cache_unavailable"] = True
        return render(request, "home/results.html", context)

    if not context["document_number_looks_invalid"]:
        matches = []
        for spec in available:
            match = spec.search(raw_document_number)
            if match:
                matches.append((spec, match))
        context["matches"] = matches
        if matches:
            # Identity (name, document type, RUES status) is core/party data,
            # the same whichever radar reports it.
            context["identity"] = matches[0][1]

    return render(request, "home/results.html", context)
