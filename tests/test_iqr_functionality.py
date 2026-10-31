"""
Tests functions used by recon analytics.
"""

import pandas as pd
import pytest

from parseus.analytics.base import (
    determine_outlier_thresholds_iqr,
    replace_with_thresholds_iqr,
)


def test_determine_outlier_thresholds_iqr_normal_case():
    df = pd.DataFrame({"ExampleColumn": [1, 2, 3, 4, 5]})
    lower_limit, upper_limit = determine_outlier_thresholds_iqr(df, "ExampleColumn")
    assert lower_limit == -1.0
    assert upper_limit == 7.0


def test_determine_outlier_thresholds_iqr_single_value():
    df = pd.DataFrame({"ExampleColumn": [5]})
    lower_limit, upper_limit = determine_outlier_thresholds_iqr(df, "ExampleColumn")
    assert lower_limit == 5
    assert upper_limit == 5


def test_determine_outlier_thresholds_iqr_identical_values():
    df = pd.DataFrame({"ExampleColumn": [3, 3, 3, 3, 3]})
    lower_limit, upper_limit = determine_outlier_thresholds_iqr(df, "ExampleColumn")
    assert lower_limit == 3
    assert upper_limit == 3


def test_determine_outlier_thresholds_iqr_different_quantiles():
    df = pd.DataFrame({"ExampleColumn": [1, 2, 3, 4, 5]})
    lower_limit, upper_limit = determine_outlier_thresholds_iqr(
        df, "ExampleColumn", th1=0.2, th3=0.8
    )
    assert lower_limit == pytest.approx(-1.8)
    assert upper_limit == pytest.approx(7.8)


def test_replace_with_thresholds_iqr_normal_case():
    "Test where no replacements occur"
    df = pd.DataFrame({"ExampleColumn": [1, 2, 3, 4, 5]})
    replace_with_thresholds_iqr(df, ["ExampleColumn"])
    assert df["ExampleColumn"].equals(pd.Series([1, 2, 3, 4, 5]))


def test_replace_with_thresholds_iqr_empty_dataframe():
    "Test that nothing is changed when an empty dataframe is passed in."
    df = pd.DataFrame(columns=["ExampleColumn"])
    replace_with_thresholds_iqr(df, ["ExampleColumn"])
    assert df.empty
