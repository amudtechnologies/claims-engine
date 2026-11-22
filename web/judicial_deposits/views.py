import dataclasses
from urllib.parse import quote, urlencode

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse

from . import core_cache, corpus_stats, history, insights, party_search, preview, radar

# How the WhatsApp message names the number, by `party.document_type`.
_DOCUMENT_REFERENCE = {"legal_entity": "el NIT", "natural_person": "la cédula"}


def _whatsapp_url(party_result) -> str:
    """wa.me link with a message that already names the number consulted,
    so whoever answers knows the case without asking."""
    reference = _DOCUMENT_REFERENCE.get(party_result.document_type, "el número")
    message = (
        f"Hola, consulté {reference} {party_result.document_number} en Amud "
        "Technologies y quiero más detalles sobre los depósitos judiciales encontrados."
    )
    return f"https://wa.me/{settings.CONTACT_WHATSAPP_NUMBER}?text={quote(message)}"


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
        context["corpus_charts"] = corpus_stats.corpus_charts()
    return render(request, "judicial_deposits/index.html", context)


def detail(request):
    """This radar's detail for one document number: the latest publication
    (or, when absent from it, the last one it appears in), then the full
    history with its aggregate charts. While the latest publication's claim
    window is open, a masked preview of its deposits ends in a WhatsApp
    "Contactar" link (no form, nothing stored)."""
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
    context["first_appearance"] = party_search.is_first_appearance(party_result, latest_period)
    if current and current.claimable:
        context["deposit_preview"] = preview.build_preview(current.summary.deposits)
        context["whatsapp_url"] = _whatsapp_url(party_result)
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
    _add_history(request, context, party_result, periods, latest_period)

    return render(request, "judicial_deposits/detail.html", context)


# `pub` value that keeps every publication closed (overrides the default).
CLOSED = "ninguna"


def _add_history(request, context, party_result, periods, latest_period) -> None:
    """The "Publicaciones anteriores" block: every publication except the
    latest one (its deposits are the block above), its charts, and the
    paginated per-publication list driven by the query string (history.py)."""
    previous = [d for d in party_result.deposits if d.period != latest_period]
    context["history_summary"] = dataclasses.replace(party_result, deposits=previous)
    context["charts"] = insights.history_charts(
        previous, [p for p in periods if p != latest_period], None
    )
    history_periods = sorted({d.period for d in previous if d.period})
    context["history_period_count"] = len(history_periods)
    context["history_first_period"] = history_periods[0] if history_periods else None

    groups = history.publication_groups(previous)
    # The most recent publication opens by default. Closing it sends
    # pub=ninguna, which matches no publication, so nothing reopens.
    opened = request.GET.get("pub") if "pub" in request.GET else (
        groups[0].period if groups else None
    )
    if not any(group.period == opened for group in groups):
        opened = None
    opened_index = next((i for i, g in enumerate(groups) if g.period == opened), 0)
    show_all = request.GET.get("todas") == "1" or opened_index >= history.VISIBLE_PUBLICATIONS

    base = {"nit": party_result.document_number}

    def url(**params) -> str:
        merged = {**base, **({"todas": "1"} if show_all else {}), **params}
        merged = {key: value for key, value in merged.items() if value not in (None, "")}
        return f"{reverse('judicial_deposits:detail')}?{urlencode(merged)}#jd-publicaciones"

    visible = groups if show_all else groups[: history.VISIBLE_PUBLICATIONS]
    context["publication_rows"] = [
        {
            "group": group,
            "open": group.period == opened,
            "url": url(pub=CLOSED if group.period == opened else group.period),
        }
        for group in visible
    ]
    context["publication_count"] = len(groups)
    context["hidden_publications"] = len(groups) - len(visible)
    context["hidden_publications_range"] = (
        f"{groups[-1].period} a {groups[len(visible)].period}" if len(groups) > len(visible) else ""
    )
    context["show_all_url"] = url(todas="1")
    if opened:
        try:
            page = int(request.GET.get("page", "1"))
        except ValueError:
            page = 1
        rows, info = history.publication_page(previous, opened, page)
        context["history_rows"] = rows
        context["history_page"] = info
        context["page_links"] = [
            {"number": number, "url": url(pub=opened, page=number) if number else None}
            for number in info.links
        ]
        context["prev_page_url"] = url(pub=opened, page=info.page - 1) if info.page > 1 else None
        context["next_page_url"] = (
            url(pub=opened, page=info.page + 1) if info.page < info.pages else None
        )
