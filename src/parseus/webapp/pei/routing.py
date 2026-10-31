"""Routing handled by daphne for websocket support."""

from django.urls import path

from .consumers import PeatLogConsumer

websocket_urlpatterns = [
    path("peat/results/log/", PeatLogConsumer.as_asgi()),
]
