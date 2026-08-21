from django.shortcuts import redirect, render
from django.utils import timezone
from judicial_deposits import core_cache, party_search


def index(request):
    return render(request, "home/index.html", {"active_nav": "home"})


def results(request):
    raw_nit = request.GET.get("nit", "").strip()
    if not raw_nit:
        return redirect("home:index")

    context = {
        "active_nav": "home",
        "raw_nit": raw_nit,
        "normalized_nit": party_search.normalize_document_number(raw_nit),
        "searched_at": timezone.localdate(),
    }

    if not core_cache.is_synced():
        context["cache_unavailable"] = True
        return render(request, "home/results.html", context)

    context["result"] = party_search.search_party(raw_nit)
    return render(request, "home/results.html", context)
