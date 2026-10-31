"""
ASGI config for the project.

It exposes the ASGI callable as a module-level variable named ``application``.

The websocket layer is optional: it is only wired up when the Channels stack is
installed *and* at least one installed app has registered websocket routes (via
``parseus.webapp.registry``). This keeps the project runnable as a plain HTTP
ASGI app when websocket-providing apps (e.g. pei) are not installed.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "parseus.webapp.project.settings")

# Initialize Django (populates the app registry, running each app's ready(),
# which is where websocket routes are registered).
django_asgi_app = get_asgi_application()


def _build_application():
    """Return an ASGI application, adding websockets only when available."""
    from parseus.webapp.registry import get_websocket_urlpatterns

    websocket_urlpatterns = get_websocket_urlpatterns()
    if not websocket_urlpatterns:
        return django_asgi_app

    try:
        from channels.auth import AuthMiddlewareStack
        from channels.routing import ProtocolTypeRouter, URLRouter
    except ImportError:
        # Channels is not installed; serve HTTP only.
        return django_asgi_app

    return ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        }
    )


application = _build_application()
