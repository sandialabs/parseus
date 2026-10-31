"""Tests for the declarative analytic capability types.

Verify the capability types behave as intended and that real built-in analytics
declare the data sources they should (read directly from each analytic's
``data_source()`` / ``requires_fit()``).
"""

from parseus.analytics.capabilities import (
    Capabilities,
    ElasticsearchSource,
    IndexQuery,
    JoblibArtifact,
    PeatFileSource,
    Supervised,
    Unsupervised,
)
from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)
from parseus.analytics.network_anomalies.excessive_conversation_analytic import (
    ExcessiveConversationAnalytic,
)
from parseus.analytics.ot_internals.peat_device_change_analytic import (
    PeatDeviceChangeAnalytic,
)


def test_training_capabilities_report_requires_fit():
    assert Supervised().requires_fit is True
    assert Unsupervised().requires_fit is False


def test_capabilities_are_immutable():
    caps = Capabilities(training=Supervised())
    try:
        caps.training = Unsupervised()  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover - dataclass(frozen=True) must forbid assignment
        raise AssertionError("Capabilities should be frozen")


def test_supervised_elasticsearch_analytic_declares_its_source():
    analytic = ExcessiveConversationAnalytic(calendar_interval="minute")

    source = analytic.data_source()

    assert analytic.requires_fit() is True
    assert isinstance(source, ElasticsearchSource)
    assert isinstance(source.run, IndexQuery)
    assert source.run.composite_agg is not None


def test_unsupervised_elasticsearch_analytic_declares_its_source():
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[])

    source = analytic.data_source()

    assert analytic.requires_fit() is False
    assert isinstance(source, ElasticsearchSource)
    assert source.run.return_fields  # declares the fields it pulls


def test_peat_analytic_declares_peat_source():
    analytic = PeatDeviceChangeAnalytic()

    assert analytic.requires_fit() is True
    assert isinstance(analytic.data_source(), PeatFileSource)


def test_joblib_artifact_carries_schema_version():
    assert JoblibArtifact().schema_version == 1
    assert JoblibArtifact(schema_version=3).schema_version == 3
