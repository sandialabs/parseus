"""Shared helpers for the PEAT change-detection analytics."""

import pandas as pd


def convert_to_df(dicts):
    """
    Changes a sequence of dictionaries into a DataFrame, setting the index to
    "@timestamp" if present.
    """
    df = pd.DataFrame(dicts)
    if "@timestamp" in df.columns:
        df = df.set_index("@timestamp")
    return df
