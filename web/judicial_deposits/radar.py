"""This radar's registration with the site shell (see home/radars.py)."""

from urllib.parse import quote

from django.urls import reverse
from home.radars import RadarMatch, RadarSpec
from home.templatetags.home_extras import cop, es_co_number

from . import core_cache, party_search


def search(raw_document_number: str) -> RadarMatch | None:
    result = party_search.search_party(raw_document_number)
    if result is None:
        return None
    claim_status = None
    if result.last_period:
        window = party_search.claim_window(result.last_period)
        claim_status = party_search.claim_status(
            window, result.source_for_period(result.last_period)
        )
    detail_url = reverse("judicial_deposits:detail")
    return RadarMatch(
        document_number=result.document_number,
        party_name=result.party_name,
        source_declared_name=result.source_declared_name,
        document_type=result.document_type,
        rues_active=result.rues_active,
        finding_count=result.deposit_count,
        total_amount_cop=result.total_amount_cop,
        detail_url=f"{detail_url}?nit={quote(result.document_number)}",
        extra={"claim_status": claim_status},
    )


def card_stats() -> list[tuple[str, str]]:
    """The same four figures as this radar's landing page ("en cifras")."""
    if not core_cache.is_synced():
        return []
    latest_period = party_search.latest_published_period()
    latest_year = latest_period.split("-")[0] if latest_period else "2026"
    party_count = party_search.total_party_count()
    return [
        (f"2017–{latest_year}", "Historial de datos públicos"),
        (es_co_number(party_search.total_court_count()), "Despachos judiciales analizados"),
        (
            f"{es_co_number(party_count / 1_000_000, 2)}M+" if party_count else "—",
            "Partes identificadas",
        ),
        (
            cop(party_search.total_claim_amount_cop()),
            "Valor total de los depósitos identificados a la fecha",
        ),
    ]


spec = RadarSpec(
    slug="depositos-judiciales",
    name="Depósitos judiciales",
    problem=(
        "Dinero constituido en procesos judiciales que prescribe a favor de la "
        "Nación si no se reclama dentro del plazo legal."
    ),
    identifies=(
        "Depósitos que la Rama Judicial publica como no reclamados, con el "
        "juzgado, el valor y la identificación de las partes."
    ),
    audience=(
        "Empresas y personas, y también los profesionales que gestionan "
        "recuperaciones."
    ),
    landing_url_name="judicial_deposits:index",
    results_row_template="judicial_deposits/_results_row.html",
    search=search,
    is_available=core_cache.is_synced,
    card_stats=card_stats,
    card_template="judicial_deposits/_card.html",
    stylesheet="css/judicial_deposits.css",
)
