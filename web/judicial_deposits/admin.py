from django.contrib import admin

from .models import ClaimWindow, ServiceRequest


@admin.register(ClaimWindow)
class ClaimWindowAdmin(admin.ModelAdmin):
    list_display = ("period", "opens_on", "closes_on")
    ordering = ("-period",)


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "request_type",
        "document_number",
        "name",
        "email",
        "phone",
        "relationship",
        "claimable_count",
        "claimable_amount_cop",
    )
    list_filter = ("request_type", "radar", "relationship")
    search_fields = ("document_number", "name", "email")
    date_hierarchy = "created_at"
    # A record of what the visitor submitted and what was claimable then.
    readonly_fields = [field.name for field in ServiceRequest._meta.fields]

    def has_add_permission(self, request):
        return False
