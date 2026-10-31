"""Backward-compatible re-exports for the analytics base module.

The runtime contract now lives in :mod:`parseus.analytics.core.analytic` and the
tabular model classes in :mod:`parseus.analytics.core.models`. This module keeps
the historical ``from parseus.analytics.base import ...`` import paths working.
"""

from parseus.analytics.core.analytic import Analytic, AnalyticContractError
from parseus.analytics.core.models import (
    Model,
    OutsideStdDevModel,
    TimestepAnomalyModel,
    determine_outlier_thresholds_iqr,
    replace_with_thresholds_iqr,
)

__all__ = [
    "Analytic",
    "AnalyticContractError",
    "Model",
    "TimestepAnomalyModel",
    "OutsideStdDevModel",
    "determine_outlier_thresholds_iqr",
    "replace_with_thresholds_iqr",
]
