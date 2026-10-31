"""
The Parseus `analytics` package is a collection of analysis classes with common
interface defined in the `base` module.
"""

from parseus.analytics.host_anomalies.sysmon_unapproved_device_analytic import (
    SysmonUnapprovedDeviceAnalytic,
)
from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)
from parseus.analytics.host_anomalies.sysmon_unapproved_user_analytic import (
    SysmonUnapprovedUserAnalytic,
)
from parseus.analytics.network_anomalies.excessive_conversation_analytic import (
    ExcessiveConversationAnalytic,
)
from parseus.analytics.network_anomalies.new_communications_analytic import (
    NewCommunicationsAnalytic,
)
from parseus.analytics.network_anomalies.port_scan_target_analytic import (
    PortScanTargetAnalytic,
)
from parseus.analytics.ot_internals import (
    PeatAuthEnumerationAnalytic,
    PeatDeviceChangeAnalytic,
    PeatFileChangeAnalytic,
    PeatFirmwareChangeAnalytic,
    PeatIOChangeAnalytic,
    PeatLogicChangeAnalytic,
    PeatProcessChangeAnalytic,
    PeatServiceChangeAnalytic,
)
from parseus.analytics.ot_network.ot_function_code_anomaly_analytic import (
    OTFunctionCodeAnomalyAnalytic,
)
from parseus.analytics.registry import (
    discover_analytics,
    get_analytic_spec,
    list_analytic_specs,
    register_analytic,
    register_spec,
)
from parseus.analytics.scpi_analytics.scpi_compare_analytic import ScpiCompareAnalytic
from parseus.analytics.scpi_analytics.scpi_value_ranges_analytic import (
    ScpiValueRangesAnalytic,
)
from parseus.analytics.spec import AnalyticSpec

__all__ = [
    "SysmonUnapprovedDeviceAnalytic",
    "SysmonUnapprovedIpAnalytic",
    "SysmonUnapprovedUserAnalytic",
    "ExcessiveConversationAnalytic",
    "PortScanTargetAnalytic",
    "NewCommunicationsAnalytic",
    "PeatAuthEnumerationAnalytic",
    "PeatDeviceChangeAnalytic",
    "PeatFileChangeAnalytic",
    "PeatFirmwareChangeAnalytic",
    "PeatIOChangeAnalytic",
    "PeatLogicChangeAnalytic",
    "PeatProcessChangeAnalytic",
    "PeatServiceChangeAnalytic",
    "OTFunctionCodeAnomalyAnalytic",
    "ScpiCompareAnalytic",
    "ScpiValueRangesAnalytic",
    "AnalyticSpec",
    "discover_analytics",
    "get_analytic_spec",
    "list_analytic_specs",
    "register_analytic",
    "register_spec",
]
