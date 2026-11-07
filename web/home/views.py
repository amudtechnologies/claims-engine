from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from . import radars


def robots_txt(request):
    """Excludes /resultados/ from crawling — it's a personalized, per-query
    utility page (also marked noindex in its own template), never a page a
    search result should point to. See docs/project-context.md's SEO
    strategy: this is both a thin-content and a privacy consideration, since
    a crawled URL could otherwise carry a real document number. The sitemap
    itself is django.contrib.sitemaps (cms/sitemaps.py), wired in urls.py."""
    lines = [
        "User-agent: *",
        "Disallow: /resultados/",
        "Disallow: /management/",
        "",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def index(request):
    context = {
        "active_nav": "home",
        "page_title": "Dinero que ya tiene dueño, identificado antes que nadie — Amud Technologies",
        "page_description": (
            "Amud Technologies identifica acreencias y oportunidades patrimoniales "
            "de empresas en Colombia — y también de personas naturales — empezando "
            "por depósitos judiciales sin reclamar. Consulte gratis con su NIT o cédula."
        ),
    }
    return render(request, "home/index.html", context)


def radares(request):
    """The radar family index. Each radar is its own app that registers a
    RadarSpec (home/radars.py); this page only lists what is registered."""
    context = {
        "active_nav": "radares",
        "page_title": "Radares activos y en desarrollo — Amud Technologies",
        "page_description": (
            "Conozca los radares de Amud Technologies: fuentes públicas "
            "colombianas que cruzamos para identificar dinero, derechos y "
            "activos asociados a una empresa o persona natural."
        ),
        "radars": [
            (spec, spec.card_stats() if spec.card_stats else [])
            for spec in radars.all_radars()
        ],
    }
    return render(request, "home/radares.html", context)


def results(request):
    raw_document_number = request.GET.get("nit", "").strip()
    if not raw_document_number:
        return redirect("home:index")

    normalized_document_number = "".join(c for c in raw_document_number if c.isdigit())
    context = {
        # The search starts from the home hero, so "Inicio" stays the active nav item.
        "active_nav": "home",
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
