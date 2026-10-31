from django.apps import AppConfig


class PeatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parseus.webapp.pei"

    def ready(self):
        from django.conf import settings

        from .app_settings import apply_defaults
        from .data_source import register as register_data_source

        apply_defaults(settings)
        register_data_source()
        self._register_websocket_routes()

        import parseus.webapp.pei.signals  # noqa: F401

    @staticmethod
    def _register_websocket_routes():
        """Register pei's websocket routes with the shared registry."""
        from parseus.webapp.registry import register_websocket_urlpatterns

        from .routing import websocket_urlpatterns

        register_websocket_urlpatterns(
            "parseus.webapp.pei", websocket_urlpatterns
        )
