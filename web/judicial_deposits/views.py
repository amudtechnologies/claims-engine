from urllib.parse import quote

from django.shortcuts import redirect, render
from django.urls import reverse

from . import core_cache, insights, party_search, radar


def _service_ld(request) -> dict:
    """schema.org Service for this landing — only what the page itself shows:
    the radar, its provider, Colombia, and the free aggregated lookup."""
    site = request.build_absolute_uri("/")
    return {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": "Radar de depósitos judiciales",
        "serviceType": "Identificación de depósitos judiciales sin reclamar",
        "description": radar.spec.problem,
        "url": request.build_absolute_uri(reverse("judicial_deposits:index")),
        "provider": {"@id": site + "#organization"},
        "areaServed": {"@type": "Country", "name": "Colombia"},
        "offers": {
            "@type": "Offer",
            "name": "Consulta gratuita",
            "description": (
                "Resumen agregado de los depósitos identificados para un NIT o una cédula."
            ),
            "price": "0",
            "priceCurrency": "COP",
        },
    }


def index(request):
    """Landing page for the radar: what it is, the legal terms, aggregate figures."""
    legacy_document_number = request.GET.get("nit", "").strip()
    if legacy_document_number:
        # The party detail used to render on this page; keep old links working.
        detail_url = reverse("judicial_deposits:detail")
        return redirect(f"{detail_url}?nit={quote(legacy_document_number)}")

    context = {
        "active_nav": "judicial_deposits",
        "page_title": (
            "Depósitos judiciales sin reclamar: consulte por NIT o cédula — Amud Technologies"
        ),
        "page_description": (
            "Consulte gratis con su NIT o cédula si aparece en los listados de "
            "depósitos judiciales sin reclamar de la Rama Judicial. Qué son, "
            "qué plazos aplican y cómo reclamarlos."
        ),
        "crumbs": [
            ("Inicio", reverse("home:index")),
            ("Radares", reverse("home:index") + "#radares"),
            (radar.spec.name, None),
        ],
        "service_ld": _service_ld(request),
        "radar_slug": radar.spec.slug,
    }
    context["stats"] = radar.card_stats()
    if core_cache.is_synced():
        context["observation_count"] = party_search.total_observation_count()
    return render(request, "judicial_deposits/index.html", context)


def detail(request):
    """This radar's detail for one document number: the latest publication
    (or, when absent from it, the last one it appears in), then the full
    history with its aggregate charts. Informational only — no collection
    or verification request (commercial work is out of scope for now)."""
    raw_document_number = request.GET.get("nit", "").strip()
    if not raw_document_number:
        return redirect("judicial_deposits:index")

    context = {
        "active_nav": "judicial_deposits",
        "page_title": "Depósitos judiciales de su consulta — Amud Technologies",
        "page_description": "Detalle de la consulta en el radar de depósitos judiciales.",
        "raw_document_number": raw_document_number,
        "results_url": f"{reverse('home:results')}?nit={quote(raw_document_number)}",
    }
    if not core_cache.is_synced():
        context["cache_unavailable"] = True
        return render(request, "judicial_deposits/detail.html", context)

    # The page's "Fuente" line names this period, from the data, never hardcoded.
    latest_period = party_search.latest_published_period()
    context["latest_period"] = latest_period
    party_result = party_search.search_party(raw_document_number)
    context["party_result"] = party_result
    if not party_result:
        return render(request, "judicial_deposits/detail.html", context)

    current = party_search.current_publication(party_result, latest_period)
    context["current"] = current
    periods = party_search.published_periods()
    context["current_charts"] = (
        insights.current_publication_charts(party_result.deposits, periods, latest_period)
        if current
        else None
    )
    # Absent from the latest publication: the last one it does appear in
    # gets the same block (figures, deadline, roles, compact charts) next.
    if current is None and party_result.last_period:
        last_appearance = party_search.publication(party_result, party_result.last_period)
        context["last_appearance"] = last_appearance
        context["last_appearance_charts"] = insights.current_publication_charts(
            party_result.deposits, periods, last_appearance.period
        )
    context["charts"] = insights.history_charts(party_result.deposits, periods, latest_period)

    return render(request, "judicial_deposits/detail.html", context)
