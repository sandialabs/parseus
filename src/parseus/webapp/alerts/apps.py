from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parseus.webapp.alerts"

    def ready(self):
        from django.conf import settings

        from .app_settings import apply_defaults
        from .periodic_tasks import register as register_periodic_tasks

        apply_defaults(settings)
        register_periodic_tasks()
