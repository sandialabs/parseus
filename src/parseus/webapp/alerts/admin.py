from django.contrib import admin

from .models import SysmonRule


@admin.register(SysmonRule)
class SysmonRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "analytic_type", "match_value", "timezone", "enabled")
    list_filter = ("analytic_type", "enabled", "timezone")
    search_fields = ("name", "match_value", "description")
