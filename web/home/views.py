from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from judicial_deposits import core_cache, party_search


def robots_txt(request):
    """Excludes /resultados/ from crawling — it's a personalized, per-query
    utility page (also marked noindex in its own template), never a page a
    search result should point to. See docs/project-context.md's SEO
    strategy: this is both a thin-content and a privacy consideration, since
    a crawled URL could otherwise carry a real document number."""
    lines = [
        "User-agent: *",
        "Disallow: /resultados/",
        "Disallow: /admin/",
        "",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    """Hand-rolled instead of django.contrib.sitemaps — avoids pulling in the
    sites framework (SITE_ID, a DB-backed Site row) for what is, today, three
    static URLs. /resultados/ is deliberately absent: it's personalized and
    already noindexed."""
    base = f"{request.scheme}://{request.get_host()}"
    pages = [
        (reverse("home:index"), "1.0", "weekly"),
        (reverse("judicial_deposits:index"), "0.9", "weekly"),
        (reverse("home:radares"), "0.6", "monthly"),
    ]
    entries = "".join(
        f"<url><loc>{base}{path}</loc><changefreq>{freq}</changefreq><priority>{priority}</priority></url>"
        for path, priority, freq in pages
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    )
    return HttpResponse(xml, content_type="application/xml")


def index(request):
    context = {
        "active_nav": "home",
        "page_title": "Dinero que ya tiene dueño, identificado antes que nadie — Amud Technologies",
        "page_description": (
            "Amud Technologies identifica dinero, derechos y activos que ya le "
            "pertenecen a personas y empresas en Colombia — empezando por "
            "depósitos judiciales sin reclamar. Consulte gratis con su NIT o cédula."
        ),
    }
    return render(request, "home/index.html", context)


def radares(request):
    """The radar family index — Radar de Acreencias is the platform; each radar
    below is one data source it searches. Cross-radar by nature (lists every
    radar, not just judicial deposits), so it lives in `home` alongside
    `results` rather than inside one radar's own app."""
    context = {
        "active_nav": "radares",
        "page_title": "Radares activos y en desarrollo — Amud Technologies",
        "page_description": (
            "Conozca los radares de Amud Technologies: fuentes públicas "
            "colombianas que cruzamos para identificar dinero, derechos y "
            "activos asociados a una persona o empresa."
        ),
    }
    if core_cache.is_synced():
        context["jd_total_amount_cop"] = party_search.total_claim_amount_cop()
        context["jd_observation_count"] = party_search.total_observation_count()
    return render(request, "home/radares.html", context)


def results(request):
    raw_document_number = request.GET.get("nit", "").strip()
    if not raw_document_number:
        return redirect("home:index")

    normalized_document_number = party_search.normalize_document_number(raw_document_number)
    context = {
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

    if not core_cache.is_synced():
        context["cache_unavailable"] = True
        return render(request, "home/results.html", context)

    if not context["document_number_looks_invalid"]:
        result = party_search.search_party(raw_document_number)
        context["result"] = result
        if result and result.last_period:
            window = party_search.claim_window(result.last_period)
            context["claim_status"] = party_search.claim_status(window)

    return render(request, "home/results.html", context)
