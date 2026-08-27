from .models import CompanyProfile


def company_profile(request):
    """Makes the company's own contact details (base.html's footer) available
    on every page without every view repeating the lookup."""
    return {"company_profile": CompanyProfile.objects.first()}
