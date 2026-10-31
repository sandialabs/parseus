"""Tests for PEI view helpers."""

from types import SimpleNamespace

from parseus.webapp.pei import views


def test_build_busy_target_display_map_uses_config_label_for_ip(monkeypatch):
    """Busy lock targets should be shown with configured device labels."""

    def fake_resolve_lock_targets(targets, target_mode):
        assert target_mode == "ip"
        return [SimpleNamespace(target=str(target)) for target in targets]

    monkeypatch.setattr(views, "resolve_lock_targets", fake_resolve_lock_targets)

    display_map = views._build_busy_target_display_map(
        ["PLC One: 192.168.1.10", "PLC Two: 192.168.1.11"],
        ["192.168.1.10", "192.168.1.11"],
        "ip",
    )

    assert views._display_busy_targets(
        ["192.168.1.11", "192.168.1.12"],
        display_map,
    ) == ["PLC Two: 192.168.1.11", "192.168.1.12"]


def test_build_busy_target_display_map_keeps_resolved_identity_for_hostname(monkeypatch):
    """Hostname labels should include the resolved lock target for clarity."""

    def fake_resolve_lock_targets(targets, target_mode):
        assert target_mode == "ip"
        assert targets == ["plc-one.local"]
        return [SimpleNamespace(target="192.168.1.10")]

    monkeypatch.setattr(views, "resolve_lock_targets", fake_resolve_lock_targets)

    display_map = views._build_busy_target_display_map(
        ["PLC One: plc-one.local"],
        ["plc-one.local"],
        "ip",
    )

    assert display_map == {"192.168.1.10": "PLC One: plc-one.local (192.168.1.10)"}
