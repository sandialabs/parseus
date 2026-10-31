"""Core building blocks for the analytics package.

`core.analytic` defines the :class:`Analytic` runtime contract shared by every
analytic, `core.models` holds the tabular model classes and IQR helpers, and
`core.alerts` builds ECS-shaped alert documents.
"""

from parseus.analytics.core.alerts import build_ecs_alert, build_ecs_baseline
from parseus.analytics.core.analytic import Analytic, AnalyticContractError
from parseus.analytics.core.models import (
    Model,
    OutsideStdDevModel,
    TimestepAnomalyModel,
    determine_outlier_thresholds_iqr,
    replace_with_thresholds_iqr,
)
from parseus.analytics.core.operator_rules import OperatorRuleMixin
from parseus.analytics.core.state import StateStore
from parseus.analytics.core.suppression import (
    DEFAULT_WINDOW,
    SuppressionWindow,
    SuppressionWindowError,
    finding_fingerprint,
    parse_window,
    window_now,
)

__all__ = [
    "Analytic",
    "AnalyticContractError",
    "OperatorRuleMixin",
    "StateStore",
    "SuppressionWindow",
    "SuppressionWindowError",
    "DEFAULT_WINDOW",
    "finding_fingerprint",
    "parse_window",
    "window_now",
    "build_ecs_alert",
    "build_ecs_baseline",
    "Model",
    "TimestepAnomalyModel",
    "OutsideStdDevModel",
    "determine_outlier_thresholds_iqr",
    "replace_with_thresholds_iqr",
]
