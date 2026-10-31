"""Models that should show up in the Django admin management page."""

from django.contrib import admin

from .models import (
    Analytic,
    AnalyticUserInput,
    TrainedModel,
    TrainedModelMetadata,
)


@admin.register(Analytic)
class AnalyticAdmin(admin.ModelAdmin):
    """Surface the active/retired tombstone state in the admin list view.

    Retired analytics (``is_active=False``) are kept rather than deleted when
    they drop out of the registry but still have trained models depending on
    them; showing the flag here is how an operator notices and acts on that.
    """

    list_display = ("name", "family", "analytic_class", "is_active")
    list_filter = ("is_active",)


# Register your models here.
admin.site.register(TrainedModel)
admin.site.register(TrainedModelMetadata)
admin.site.register(AnalyticUserInput)
