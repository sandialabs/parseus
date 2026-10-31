"""Every built-in analytic declares its capabilities via ``@register_analytic``.

Pins that each registered analytic declares an explicit data-source / training /
persistence capability (the descriptor is the sole source of truth), that
default output indices are present, and that class paths resolve.
"""

import pytest

# Importing the analytics package runs every @register_analytic decorator,
# populating the registry as a side effect (hence the F401 exemption).
import parseus.analytics  # noqa: F401
from parseus.analytics.capabilities import DataSource, Supervised
from parseus.analytics.registry import list_analytic_specs
from parseus.analytics.spec import load_class

# Keys registered by the built-in analytic decorators.
_EXPECTED_KEYS = {
    "ExcessiveConversationAnalytic",
    "PortScanTargetAnalytic",
    "OTFunctionCodeAnomalyAnalytic",
    "NewCommunicationsAnalytic",
    "ScpiCompareAnalytic",
    "ScpiValueRangesAnalytic",
    "SysmonUnapprovedUserAnalytic",
    "SysmonUnapprovedIpAnalytic",
    "SysmonUnapprovedDeviceAnalytic",
    "PeatDeviceChangeAnalytic",
    "PeatFileChangeAnalytic",
    "PeatServiceChangeAnalytic",
    "PeatProcessChangeAnalytic",
    "PeatIOChangeAnalytic",
    "PeatAuthEnumerationAnalytic",
    "PeatFirmwareChangeAnalytic",
    "PeatLogicChangeAnalytic",
}


def _registered_specs():
    return {spec.key: spec for spec in list_analytic_specs()}


def test_all_builtin_analytics_are_registered():
    registered = set(_registered_specs())
    missing = _EXPECTED_KEYS - registered
    assert not missing, f"Analytics not registered via decorator: {sorted(missing)}"


@pytest.mark.parametrize("key", sorted(_EXPECTED_KEYS))
def test_analytic_declares_its_capabilities(key):
    spec = _registered_specs()[key]

    # Every built-in analytic declares its data-source / training / persistence.
    assert isinstance(spec.data_source, DataSource), f"{key} missing data_source"
    assert spec.training is not None, f"{key} missing training"
    assert spec.persistence is not None, f"{key} missing persistence"
    # The declared training matches the class's own requires_fit().
    assert spec.training.requires_fit == spec.analytic_class.requires_fit(), (
        f"{key}: declared requires_fit={spec.training.requires_fit} but class "
        f"reports {spec.analytic_class.requires_fit()}"
    )


def test_supervised_network_analytics_declared_correctly():
    specs = _registered_specs()
    for key in ("ExcessiveConversationAnalytic", "PortScanTargetAnalytic"):
        assert isinstance(specs[key].training, Supervised)


def test_out_idx_defaults_present_for_every_builtin():
    for key, spec in _registered_specs().items():
        if key not in _EXPECTED_KEYS:
            continue
        assert spec.out_idx.get("index_name"), f"{key} missing default out_idx"


def test_class_paths_resolve():
    for key in _EXPECTED_KEYS:
        spec = _registered_specs()[key]
        assert load_class(spec.class_path) is spec.analytic_class
