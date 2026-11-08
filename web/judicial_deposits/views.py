from urllib.parse import quote

from django.shortcuts import redirect, render
from django.urls import reverse

from . import core_cache, insights, party_search, radar
from .forms import ServiceRequestForm
from .models import ServiceRequest


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
    (deadline and the collection request), then the full history with its
    aggregate charts and the verification request. Both requests post back
    here and land on this same page."""
    raw_document_number = request.GET.get("nit", "").strip()
    if not raw_document_number:
        return redirect("judicial_deposits:index")

    detail_url = f"{reverse('judicial_deposits:detail')}?nit={quote(raw_document_number)}"
    context = {
        "active_nav": "judicial_deposits",
        "page_title": "Depósitos judiciales de su consulta — Amud Technologies",
        "page_description": "Detalle de la consulta en el radar de depósitos judiciales.",
        "raw_document_number": raw_document_number,
        "detail_url": detail_url,
        "results_url": f"{reverse('home:results')}?nit={quote(raw_document_number)}",
        "request_sent": request.GET.get("solicitud") == "enviada",
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
    context["charts"] = insights.history_charts(party_result.deposits, periods, latest_period)

    requested_type = request.GET.get("solicitud")
    form = None
    if request.method == "POST":
        form = ServiceRequestForm(request.POST)
        if form.is_valid():
            request_type = form.cleaned_data["request_type"]
            claimable = current is not None and current.claimable
            if request_type == ServiceRequest.RequestType.COLLECTION and not claimable:
                form.add_error(None, "Ya no hay depósitos vigentes para cobrar en esta consulta.")
            else:
                service_request = form.save(commit=False)
                service_request.document_number = party_result.document_number
                service_request.radar = radar.spec.slug
                service_request.claimable_count = (
                    current.summary.deposit_count if claimable else 0
                )
                service_request.claimable_amount_cop = (
                    current.summary.total_amount_cop if claimable else 0
                )
                service_request.save()
                # TODO: notify the team by email about the new request — no
                # outgoing mail is configured yet; requests are read in the admin.
                return redirect(f"{detail_url}&solicitud=enviada#solicitud-enviada")
        requested_type = form.data.get("request_type")
    if requested_type not in ServiceRequest.RequestType.values:
        requested_type = None
    context["form"] = form or ServiceRequestForm(
        initial={"request_type": requested_type or ServiceRequest.RequestType.VERIFICATION}
    )
    # Server-side open state: re-shows the form after a validation error, and
    # opens it for ?solicitud=<type> links when JavaScript is off.
    context["form_open"] = requested_type is not None
    context["form_is_collection"] = requested_type == ServiceRequest.RequestType.COLLECTION
    return render(request, "judicial_deposits/detail.html", context)
