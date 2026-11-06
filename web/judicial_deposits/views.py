from urllib.parse import quote

from django.shortcuts import redirect, render
from django.urls import reverse

from . import core_cache, party_search


def index(request):
    """Landing page for the radar: what it is, the legal terms, aggregate figures."""
    legacy_document_number = request.GET.get("nit", "").strip()
    if legacy_document_number:
        # The party detail used to render on this page; keep old links working.
        detail_url = reverse("judicial_deposits:detail")
        return redirect(f"{detail_url}?nit={quote(legacy_document_number)}")

    context = {
        "active_nav": "judicial_deposits",
        "page_title": "Cómo saber si tiene un depósito judicial sin reclamar — Amud Technologies",
        "page_description": (
            "Consulte gratis si el NIT de su empresa (o su cédula, si es persona "
            "natural) aparece en depósitos judiciales sin reclamar en Colombia — "
            "qué son, cuánto tiempo tiene para reclamarlos y cómo hacerlo."
        ),
    }
    if core_cache.is_synced():
        context["observation_count"] = party_search.total_observation_count()
        context["court_count"] = party_search.total_court_count()

        party_count = party_search.total_party_count()
        if party_count:
            context["party_count_millions"] = round(party_count / 1_000_000, 3)

        context["total_amount_cop"] = party_search.total_claim_amount_cop()

        latest_period = party_search.latest_published_period()
        if latest_period:
            context["latest_year"] = latest_period.split("-")[0]
    return render(request, "judicial_deposits/index.html", context)


def detail(request):
    """This radar's detail for one document number: totals, per-period
    summaries and claim-window status."""
    raw_document_number = request.GET.get("nit", "").strip()
    if not raw_document_number:
        return redirect("judicial_deposits:index")

    context = {
        "active_nav": "judicial_deposits",
        "page_title": "Depósitos judiciales de su consulta — Amud Technologies",
        "page_description": "Detalle de la consulta en el radar de depósitos judiciales.",
        "raw_document_number": raw_document_number,
    }
    if not core_cache.is_synced():
        context["cache_unavailable"] = True
        return render(request, "judicial_deposits/detail.html", context)

    party_result = party_search.search_party(raw_document_number)
    context["party_result"] = party_result
    if party_result:
        latest_period = party_search.latest_published_period()
        context["corpus_latest_period"] = latest_period
        if party_result.last_period:
            last = party_result.last_period
            window = party_search.claim_window(last)
            source = party_result.source_for_period(last)
            context["party_last_active_period"] = last
            context["party_last_active_period_result"] = party_result.for_period(last)
            context["party_last_active_period_window"] = window
            context["party_last_active_period_status"] = party_search.claim_status(window, source)
            context["party_is_current_publication"] = last == latest_period
    return render(request, "judicial_deposits/detail.html", context)
