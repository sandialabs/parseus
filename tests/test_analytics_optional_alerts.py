"""Tests for analytics treating alerts as an optional dependency."""

from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)
from parseus.webapp.analytics import utility_analytics


def test_sysmon_rules_empty_when_alerts_not_installed(monkeypatch):
    """_get_sysmon_rules returns [] when alerts is not installed."""
    from django.apps import apps as django_apps

    real_is_installed = django_apps.is_installed

    def fake_is_installed(name):
        if name == "parseus.webapp.alerts":
            return False
        return real_is_installed(name)

    monkeypatch.setattr(django_apps, "is_installed", fake_is_installed)
    assert utility_analytics._get_sysmon_rules("SysmonUnapprovedIpAnalytic") == []


def test_with_ui_managed_rules_noop_without_alerts(monkeypatch):
    """Rule merging is a no-op when alerts is unavailable."""
    monkeypatch.setattr(
        utility_analytics, "_get_sysmon_rules", lambda class_name: []
    )
    init_args = {"existing": 1}
    result = utility_analytics.with_operator_rules(
        SysmonUnapprovedIpAnalytic, init_args
    )
    assert result == {"existing": 1}


def test_with_ui_managed_rules_merges_when_present(monkeypatch):
    """Rules are merged into the analytic's declared init arg when available."""
    monkeypatch.setattr(
        utility_analytics, "_get_sysmon_rules", lambda class_name: [{"r": 1}]
    )
    result = utility_analytics.with_operator_rules(
        SysmonUnapprovedIpAnalytic, {}
    )
    assert result["ip_rules"] == [{"r": 1}]
