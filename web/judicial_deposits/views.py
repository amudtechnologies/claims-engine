from django.shortcuts import render
from django.utils import timezone

from . import core_cache, party_search
from .models import ClaimWindow


def _claim_window(period: str | None) -> ClaimWindow | None:
    if not period:
        return None
    return ClaimWindow.objects.filter(period=period).first()


def _claim_status(window: ClaimWindow | None) -> str | None:
    """"reclamable" / "no_reclamable" for a configured claim window, or None
    when no window has been configured for the period — a permanent-valid
    unset state, not an error (see ClaimWindow's docstring)."""
    if not window:
        return None
    return "reclamable" if timezone.localdate() <= window.closes_on else "no_reclamable"


def index(request):
    context = {"active_nav": "judicial_deposits"}
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

        raw_nit = request.GET.get("nit", "").strip()
        if raw_nit:
            party_result = party_search.search_party(raw_nit)
            context["party_result"] = party_result
            if party_result and latest_period:
                context["corpus_latest_period"] = latest_period
            if party_result and party_result.last_period:
                context["party_last_active_period"] = party_result.last_period
                context["party_last_active_period_result"] = party_result.for_period(
                    party_result.last_period
                )
                window = _claim_window(party_result.last_period)
                context["party_last_active_period_window"] = window
                context["party_last_active_period_status"] = _claim_status(window)
                context["party_is_current_publication"] = party_result.last_period == latest_period
    return render(request, "judicial_deposits/index.html", context)
