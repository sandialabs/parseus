"""Tests for Sysmon host anomaly analytics."""

from parseus.analytics.host_anomalies.sysmon_unapproved_device_analytic import (
    SysmonUnapprovedDeviceAnalytic,
)
from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)
from parseus.analytics.host_anomalies.sysmon_unapproved_user_analytic import (
    SysmonUnapprovedUserAnalytic,
)


def test_sysmon_ip_analytic_uses_raw_documents_and_preserves_repeated_events():
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[])
    docs = [
        {
            "@timestamp": "2026-01-01T00:00:01Z",
            "winlog": {"event_data": {"SourceAddress": "192.0.2.10"}},
        },
        {
            "@timestamp": "2026-01-01T00:00:02Z",
            "winlog": {"event_data": {"SourceAddress": "192.0.2.10"}},
        },
    ]

    alerts = analytic.run_on_data(docs, start=None, end=None)

    run_spec = analytic.data_source().run
    assert run_spec.composite_agg is None
    assert run_spec.return_fields == ["winlog.event_data.SourceAddress", "@timestamp"]
    assert len(alerts) == 2
    assert [alert["@timestamp"] for alert in alerts] == [
        "2026-01-01T00:00:01Z",
        "2026-01-01T00:00:02Z",
    ]
    assert [alert["source"]["ip"] for alert in alerts] == [
        "192.0.2.10",
        "192.0.2.10",
    ]


def test_sysmon_device_analytic_uses_raw_documents_and_preserves_repeated_events():
    analytic = SysmonUnapprovedDeviceAnalytic(known_good_devices=[])
    docs = [
        {
            "@timestamp": "2026-01-01T00:00:01Z",
            "winlog": {"event_data": {"DeviceId": "USB\\VID_1234"}},
        },
        {
            "@timestamp": "2026-01-01T00:00:02Z",
            "winlog": {"event_data": {"DeviceId": "USB\\VID_1234"}},
        },
    ]

    alerts = analytic.run_on_data(docs, start=None, end=None)

    assert analytic.data_source().run.composite_agg is None
    assert analytic.data_source().run.return_fields == [
        "winlog.event_data.DeviceId",
        "@timestamp",
    ]
    assert len(alerts) == 2
    assert [alert["@timestamp"] for alert in alerts] == [
        "2026-01-01T00:00:01Z",
        "2026-01-01T00:00:02Z",
    ]
    assert [alert["device"]["id"] for alert in alerts] == [
        "USB\\VID_1234",
        "USB\\VID_1234",
    ]


def test_sysmon_user_analytic_uses_raw_documents_and_preserves_repeated_events():
    analytic = SysmonUnapprovedUserAnalytic(known_good_users=[])
    docs = [
        {
            "@timestamp": "2026-01-01T00:00:01Z",
            "winlog": {"event_data": {"TargetUserName": "operator"}},
        },
        {
            "@timestamp": "2026-01-01T00:00:02Z",
            "winlog": {"event_data": {"TargetUserName": "operator"}},
        },
    ]

    alerts = analytic.run_on_data(docs, start=None, end=None)

    assert analytic.data_source().run.composite_agg is None
    assert analytic.data_source().run.return_fields == [
        "winlog.event_data.TargetUserName",
        "@timestamp",
    ]
    assert len(alerts) == 2
    assert [alert["@timestamp"] for alert in alerts] == [
        "2026-01-01T00:00:01Z",
        "2026-01-01T00:00:02Z",
    ]
    assert [alert["user"]["name"] for alert in alerts] == ["operator", "operator"]


def test_sysmon_transforms_still_accept_legacy_composite_buckets():
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[])
    docs = [
        {
            "key": {"host_ip": "192.0.2.10"},
            "first_timestamp": {
                "hits": {
                    "hits": [
                        {"_source": {"@timestamp": "2026-01-01T00:00:01Z"}}
                    ]
                }
            },
        }
    ]

    alerts = analytic.run_on_data(docs, start=None, end=None)

    assert len(alerts) == 1
    assert alerts[0]["@timestamp"] == "2026-01-01T00:00:01Z"
    assert alerts[0]["source"]["ip"] == "192.0.2.10"
