from . import radars
from .models import CompanyProfile


def company_profile(request):
    """Makes the company's own contact details (base.html's footer) available
    on every page without every view repeating the lookup."""
    return {"company_profile": CompanyProfile.objects.first()}


def site_radars(request):
    """Active radars for base.html's footer, from the registry — the shell
    links every radar landing without importing any specific radar."""
    return {"site_radars": [r for r in radars.all_radars() if r.is_active]}
