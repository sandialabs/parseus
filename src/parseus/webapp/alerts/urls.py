"""Module linking url patterns to a view for the alerts app."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.alerts_home, name="alerts_home"),
    path("rules/", views.sysmon_rules, name="sysmon_rules"),
    path("rules/new/", views.sysmon_rule_create, name="sysmon_rule_create"),
    path("rules/<int:pk>/edit/", views.sysmon_rule_update, name="sysmon_rule_update"),
    path("rules/<int:pk>/delete/", views.sysmon_rule_delete, name="sysmon_rule_delete"),
    path("alert-query/", views.alert_query, name="alerts_alert_query"),
    path("alert-stream/", views.alert_stream, name="alerts_alert_stream"),
    path("clear-all/", views.clear_all_data, name="alerts_clear_all"),
    path("handle-alerts/", views.handle_alerts, name="alerts_handle_alerts"),
    path("monitor-health/", views.ingestor_health, name="alerts_monitor_health"),
]
