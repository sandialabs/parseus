"""Tabular model classes and helpers used by analytic logic.

These encapsulate the sklearn-style, `pandas.DataFrame`-oriented logic that some
analytics delegate to (`Analytic.logic_`): a base :class:`Model`, the
:class:`TimestepAnomalyModel` anomaly-score contract, the concrete
:class:`OutsideStdDevModel`, and the IQR outlier helpers.
"""

import logging
import warnings
from typing import Any, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "Model",
    "TimestepAnomalyModel",
    "OutsideStdDevModel",
    "determine_outlier_thresholds_iqr",
    "replace_with_thresholds_iqr",
]


def _default_dataframe_to_array(data_frame):
    # this needs to be at the global level so it can get pickled
    return data_frame.values


class Model:
    """
    An abstract class for encapsulating logic for an analytic which operates on tabular data

    :param callable dataframe_to_array: A callback for converting a `pandas.DataFrame`
                                        into a `numpy.ndarray`. If None (default), it
                                        will use the `pandas.DataFrame.values` property.
    """

    def __init__(self, dataframe_to_array: callable = None, **kwargs):
        self.dataframe_to_array = dataframe_to_array or _default_dataframe_to_array
        self._log = None
        super().__init__()  # **kwargs)

    @property
    def logger(self):
        """
        :return: logger
        """
        if self._log is None:
            self._log = logging.Logger(
                name=self.__class__.__name__, level=logging.WARNING
            )
        return self._log

    @logger.setter
    def logger(self, log):
        """
        :param log: Sets a pre-existing log instance as part of the Model's attributes
        :return: None
        """
        self._log = log

    def fit_table(self, *table_list, sample_weight_function: callable = None):
        """
        Fits the logic on a set of `pandas.DataFrame` objects

        :param table_list: The DataFrames on which to fit the analytic logic, where each
                           frame's index is likely a `pandas.DateTimeIndex`
        :param callable sample_weight_function: A function taking one of the `pandas.DataFrame`
                                                objects and returning a numpy array of sample
                                                weights corresponding to each row
        """

    def run_table(
        self, previous_state: Any, table: pd.DataFrame, **other_sources
    ) -> Tuple[Any, Any]:
        """
        Runs the analytic logic and returns the results of the model. The return type
        will depend on the child class's implementation.

        :param previous_state: The previous state, in the case of stateful logic
        :param pandas.DataFrame table: The input `pandas.DataFrame`, where the index is
                                       likely a `pandas.DatetimeIndex`
        :param other_sources: Documents from any other data sources
        :return: A tuple :code:`(new_state, result)`, where the type of :code:`result`
                 depends on the method implementation
        """
        raise NotImplementedError

    def state_dict(self) -> dict:
        """Return this model's persistable state as a plain mapping."""
        to_save = dict(vars(self))
        for key, value in list(to_save.items()):
            if isinstance(value, (logging.Logger, logging.Handler)):
                if key not in ("_log",):
                    # this is an attribute that we don't know about, so let's warn
                    # the caller before dropping it
                    warnings.warn(f"Cannot serialise '{key}'. Skipping.")
                to_save.pop(key)
        return to_save

    def load_state_dict(self, state: dict) -> None:
        """Restore this model's state from a mapping produced by :meth:`state_dict`."""
        # pylint: disable=access-member-before-definition
        self.__dict__ = state
        if not hasattr(self, "_log"):
            self._log = None  # set this because it won't be in the state

    def __getstate__(self):
        """Object-protocol hook (e.g. ``copy.deepcopy``); delegates to :meth:`state_dict`."""
        return self.state_dict()

    def __setstate__(self, state):
        """Object-protocol hook; delegates to :meth:`load_state_dict`."""
        self.load_state_dict(state)


class TimestepAnomalyModel(Model):
    """
    An abstract class for encapsulating logic for returning an anomaly score
    on each row of a `pandas.DataFrame`

    :param kwargs: Passed to :meth:`Model.__init__ <parseus.analytics.core.models.Model>`
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.scale_ = 1.0

    def run_table(
        self, previous_state: Any, table: pd.DataFrame, **other_sources
    ) -> Tuple[Any, pd.Series]:
        """
        Runs the analytic logic and returns the `pandas.Series` of anomaly
        scores for each timestep

        :param previous_state: The previous state, in the case of stateful logic
        :param table: The `pandas.DataFrame` to use for anomaly detection, where
                      the index is likely a `pandas.DatetimeIndex`
        :param other_sources: Documents from any other data sources
        :return: A tuple :code:`(new_state, anomaly_scores)`, where
                :code:`anomaly_scores` is a `pandas.Series` object whose index
                (and thus length) is the same as that of 'table'.
        """
        raise NotImplementedError

    def _update_scale(
        self, *training_data_frames, sample_weight_function: callable = None
    ):
        """
        Updates the :code:`self.scale_` attribute to ensure that running these inputs
        would result in an average anomaly score of 1

        :param training_data_frames: The `pandas.DataFrame` objects to use
        :param callable sample_weight_function: A function taking one of the DataFrames
                                                and returning a numpy array of sample
                                                weights corresponding to each row
        """
        # scale it
        run_results = pd.concat(
            [
                self.run_table(None, training_df)[1]
                for training_df in training_data_frames
            ]
        )
        if sample_weight_function is None:
            run_weighted_mean = run_results.mean()
        else:
            sample_weights = np.concatenate(
                [
                    sample_weight_function(training_df)
                    for training_df in training_data_frames
                ]
            )
            run_weighted_mean = np.sum(run_results.values * sample_weights) / np.sum(
                sample_weights
            )
        if run_weighted_mean <= 0:
            raise ValueError(
                "The mean results on the training set were zero or negative."
            )
        self.scale_ = 1 / run_weighted_mean

    def column_importances(self, table: pd.DataFrame, **other_sources) -> pd.Series:
        """
        For each column, computes an importance factor that indicates how critical that
        column was in determining the final anomaly score

        :param pd.DataFrame table: The data which will be used to compute the importances
        :param other_sources: Other data sources passed to the model's run_table() method
        :return: A `pd.Series` of column name => importance score, where the importance
                 scores sum to 1
        """
        # get the anomaly scores with no scrambling
        _, original = self.run_table(None, table, **other_sources)
        # scramble the columns and measure the new anomaly scores
        scrambled_results = []
        for column in table.columns:
            # scramble this column
            scrambled_table = table.copy()
            this_column = scrambled_table.loc[:, column].values
            np.random.shuffle(this_column)
            scrambled_table.loc[:, column] = this_column
            # measure new scores
            scrambled_results.append(
                self.run_table(None, scrambled_table, **other_sources)[1]
            )
        # combine results
        importances = np.array(
            [max(0, (scrambled - original).sum()) for scrambled in scrambled_results],
            dtype=float,
        )
        importances /= np.maximum(importances.sum(), 1e-10)
        return pd.Series(dict(zip(table.columns, importances)))


# These Functions found at:
# https://medium.com/analytics-vidhya/removing-outliers-understanding-how-and-what-behind-the-magic-18a78ab480ff


def determine_outlier_thresholds_iqr(dataframe, col_name, th1=0.25, th3=0.75):
    """
    returns outlier thresholds (upper and lower) for Interquartile Range (IQR)
    """
    quartile1 = dataframe[col_name].quantile(th1)
    quartile3 = dataframe[col_name].quantile(th3)
    iqr = quartile3 - quartile1
    upper_limit = quartile3 + 1.5 * iqr
    lower_limit = quartile1 - 1.5 * iqr
    return lower_limit, upper_limit


def replace_with_thresholds_iqr(dataframe, cols, th1=0.05, th3=0.95):
    """
    Replace values that are outside the Interquartile Range with the
    threshold values.
    """
    for col_name in cols:
        lower_limit, upper_limit = determine_outlier_thresholds_iqr(
            dataframe, col_name, th1, th3
        )
        if dataframe[
            (dataframe[col_name] > upper_limit) | (dataframe[col_name] < lower_limit)
        ].any(axis=None):
            if lower_limit < 0:
                # We don't want to replace with negative values.
                dataframe.loc[(dataframe[col_name] > upper_limit), col_name] = (
                    upper_limit
                )
            else:
                dataframe.loc[(dataframe[col_name] < lower_limit), col_name] = (
                    lower_limit
                )
                dataframe.loc[(dataframe[col_name] > upper_limit), col_name] = (
                    upper_limit
                )


class OutsideStdDevModel(TimestepAnomalyModel):
    """
    Analytic that reports when a source is having an unusual number of
    IPs and IP conversations.
    """

    def __init__(self, **kwargs):
        """
        Sets up the analytic to receive packets, and store the
        source and destination IPs from those packets.
        """
        super().__init__(**kwargs)
        self.stats_df = pd.DataFrame()

    def fit_table(self, *table_list, sample_weight_function: callable = None):
        "Builds table of statistics from training data"
        for table in table_list:
            mean_df = table.mean().rename("mean").to_frame()
            std = table.std().rename("std")
            self.stats_df = pd.concat(
                [self.stats_df, mean_df.merge(std, left_index=True, right_index=True)]
            )
        self.stats_df.fillna(0, inplace=True)

    def run_table(self, previous_state, table, buffer=0, **other_sources):
        """
        Finds columns in the table that have value count exceeding 2 stdeviations from mean.
        Creates alerts in those cases.
        """
        results = pd.DataFrame()
        for col in table.columns:
            if col not in self.stats_df.index:
                continue
            alert = table.loc[
                table[col]
                > self.stats_df.loc[col]["mean"]
                + (self.stats_df.loc[col]["std"] * 2)
                + buffer
            ][col]
            if not alert.empty:
                results = pd.concat([results, alert.rename(col).to_frame()], axis=1)
        return [], results.sort_index()
