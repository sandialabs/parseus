"""General routing."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.registers, name="registers"),
    path("network/", views.get_ot_network, name="ot_network_analysis"),
    path("query/", views.registers_query, name="registers_query"),
    path("query/fc/", views.function_codes_query, name="function_codes_query"),
    path("state/", views.state, name="state"),
    path("state/state/", views.state_data, name="state_data"),
]
