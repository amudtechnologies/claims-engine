from django.shortcuts import render

from . import core_cache, party_search


def index(request):
    context = {
        "active_nav": "judicial_deposits",
        "page_title": "Cómo saber si tiene un depósito judicial sin reclamar — Amud Technologies",
        "page_description": (
            "Consulte gratis si su NIT o cédula aparece en depósitos judiciales "
            "sin reclamar en Colombia — qué son, cuánto tiempo tiene para "
            "reclamarlos y cómo hacerlo."
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

        raw_document_number = request.GET.get("nit", "").strip()
        if raw_document_number:
            party_result = party_search.search_party(raw_document_number)
            context["party_result"] = party_result
            if party_result and latest_period:
                context["corpus_latest_period"] = latest_period
            if party_result and party_result.last_period:
                context["party_last_active_period"] = party_result.last_period
                context["party_last_active_period_result"] = party_result.for_period(
                    party_result.last_period
                )
                window = party_search.claim_window(party_result.last_period)
                context["party_last_active_period_window"] = window
                context["party_last_active_period_status"] = party_search.claim_status(window)
                context["party_is_current_publication"] = party_result.last_period == latest_period
    return render(request, "judicial_deposits/index.html", context)
