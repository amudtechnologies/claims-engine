from django.contrib import admin

from .models import CompanyProfile, Radar


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "nit", "phone", "email")


@admin.register(Radar)
class RadarAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "display_order", "is_published")
    list_filter = ("status", "is_published")
    prepopulated_fields = {"slug": ("name",)}
