from django.contrib import admin

from .models import ClaimWindow


@admin.register(ClaimWindow)
class ClaimWindowAdmin(admin.ModelAdmin):
    list_display = ("period", "opens_on", "closes_on")
    ordering = ("-period",)
