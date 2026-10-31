"""Module for configuring the Analytics app in Django."""

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parseus.webapp.analytics"

    def ready(self):
        from .app_settings import configure_logging
        from .periodic_tasks import register as register_periodic_tasks

        configure_logging()
        register_periodic_tasks()
