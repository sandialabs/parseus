"""
Contains generic utility functions that are shared among the
analytics classes
"""

import datetime
from datetime import timezone
import warnings

import numpy as np
import pandas as pd

from parseus.preprocessors.reg_ops import TIMESTAMP
from parseus.util.datetime_utils import datetime_parser
from parseus.util.numerical import nanaverage


def _get_limit(reg_state_or_ops, aggregator):
    """
    Finds the timestamp of the earliest or latest document (depending on
    aggregator) from a reg_state or reg_ops object

    :param reg_state_or_ops: The reg_state or reg_ops object
    :param aggregator: The aggregator to use to find the desired timestamp (min
        or max normally)
    :return: The parsed timestamp of the first packet
    """
    default = datetime.datetime(1970, 1, 1, tzinfo=timezone.utc)
    if not isinstance(reg_state_or_ops, pd.DataFrame):
        # it's a reg_ops object
        return datetime_parser(
            aggregator(
                (packet[TIMESTAMP] for packet in reg_state_or_ops), default=default
            )
        )

    timestamps = reg_state_or_ops.index
    if timestamps.empty:
        return default

    return datetime_parser(aggregator(timestamps))


def get_start(reg_state_or_ops):
    """
    Finds the timestamp of the earliest document from a reg_state or reg_ops
    object

    :param reg_state_or_ops: The reg_state or reg_ops object
    :return: The parsed timestamp of the first packet
    """
    return _get_limit(reg_state_or_ops, min)


def get_end(reg_state_or_ops):
    """
    Finds the timestamp of the last document from a reg_state or reg_ops
    object

    :param reg_state_or_ops: The reg_state or reg_ops object
    :return: The parsed timestamp of the last packet
    """
    return _get_limit(reg_state_or_ops, max)


def build_stats_frame(data_frame: pd.DataFrame, weights=None):
    """
    Creates a stats series for all columns of a reg_state

    :param data_frame: The data frame to analyze
    :param weights: The sample weights for each row. If unspecified, all rows
        will be weighted equally
    :return: A data frame containing the various stats, where the columns are
        the original columns and the rows are the stats
    """

    # get the stats that don't depend on the weights
    # mode is a bit weird and needed reformatting
    modes = data_frame.mode(axis=0)
    stats_dict = {
        "Min": data_frame.min(axis=0).values,
        "Max": data_frame.max(axis=0).values,
        "Med": data_frame.median(axis=0).values,
        "Mode": (
            modes.iloc[0].values
            if modes.shape[0] > 0
            else np.ones((modes.shape[1],)) * np.nan
        ),
    }

    # now the stats that do
    if weights is not None:
        stats_dict["Mean"] = nanaverage(data_frame, axis=0, weights=weights)
        mean_expanded = np.expand_dims(stats_dict["Mean"], axis=0)
        variance = nanaverage(
            (data_frame.values - mean_expanded) ** 2, axis=0, weights=weights
        )

        stats_dict["Var"] = variance
        stats_dict["Std"] = np.sqrt(variance)
        stats_dict["Mad"] = nanaverage(
            np.abs(data_frame.values - mean_expanded), axis=0, weights=weights
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            stats_dict["Skew"] = nanaverage(
                (data_frame.values - mean_expanded) ** 3, axis=0, weights=weights
            ) / variance ** (3 / 2)
            stats_dict["Kurt"] = (
                nanaverage(
                    (data_frame.values - mean_expanded) ** 4, axis=0, weights=weights
                )
                / variance**2
            )
    else:
        stats_dict["Mean"] = data_frame.mean(axis=0).values
        stats_dict["Var"] = data_frame.var(axis=0, ddof=0).values
        stats_dict["Std"] = data_frame.std(axis=0, ddof=0).values
        stats_dict["Skew"] = data_frame.skew(axis=0).values
        stats_dict["Kurt"] = data_frame.kurt(axis=0).values

    # put them all together
    names = ["Min", "Max", "Mean", "Med", "Mode", "Var", "Std", "Skew", "Kurt"]
    return pd.DataFrame(
        [stats_dict[name] for name in names], columns=data_frame.columns, index=names
    )
