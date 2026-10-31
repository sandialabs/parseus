"""
Contains generic utility functions that are shared among the Parseus analytics classes
"""

import warnings
from typing import Iterable, Union

import numpy as np
import pandas as pd
from sklearn.impute import MissingIndicator, SimpleImputer
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.utils.extmath import weighted_mode

from parseus.util.numerical import inv_robust_log_adjust, nanaverage, robust_log_adjust


# https://stackoverflow.com/questions/21844024/weighted-percentile-using-numpy
# modified to work with NaNs and matrices
def nanquantile(
    values: np.ndarray,
    quantiles: Iterable[Union[float, int]],
    sample_weight=None,
    values_sorted=False,
    axis=None,
):
    """
    Very close to numpy.percentile, but supports weights

    :param np.ndarray values: The data to be analyzed
    :param quantiles: array-like with many quantiles needed, on the interval [0, 100]
    :type quantiles: iterable(float or int)
    :param sample_weight: array-like of the same length as `array`
    :param values_sorted: bool, if True, then will avoid sorting of initial array
    :param axis: The axis to measure along, similar to numpy's axis parameters. Only used when values.ndim == 2
    :return: numpy.ndarray with computed quantiles.
    :raises ValueError: When there is a mismatch between the 'axis' parameter and the dimensionality of the input or
        sample weights, or when the quantiles are invalid
    """
    values = np.array(values)
    quantiles = np.array(quantiles)

    if values.ndim == 2:
        if axis is None:
            raise ValueError("With a 2-dimensional array, you must specify an axis")
        if axis in (0, -2):
            values = values.T
        return np.array(
            [
                nanquantile(
                    values[i], quantiles, sample_weight, values_sorted=values_sorted
                )
                for i in range(values.shape[0])
            ]
        ).T
    if axis is not None:
        raise ValueError(
            "'axis' can only be set when operating on a two-dimensional object"
        )
    if values.ndim > 2:
        raise ValueError("'values' must have no more than 2 dimensions")

    if sample_weight is None:
        sample_weight = np.ones(len(values))
    elif sample_weight.ndim != 1:
        raise ValueError("'sample_weight' must be one-dimensional")
    elif sample_weight.size != values.size:
        raise ValueError(
            "The shapes of 'values' %s and 'sample_weight' %s do not match"
            % (str(values.shape), str(sample_weight.shape))
        )

    sample_weight = np.array(sample_weight)
    if not np.all(quantiles >= 0) or not np.all(quantiles <= 100):
        raise ValueError("Quantiles should be in [0, 100]")
    quantiles /= 100

    # ditch the NaNs
    nan_mask = ~np.isnan(values)
    values = values[nan_mask]
    sample_weight = sample_weight[nan_mask]

    if not values_sorted:
        sorter = np.argsort(values)
        values = values[sorter]
        sample_weight = sample_weight[sorter]

    weighted_quantiles = np.cumsum(sample_weight) - 0.5 * sample_weight
    weighted_quantiles /= np.sum(sample_weight)
    return np.interp(quantiles, weighted_quantiles, values)


class WeightedSimpleImputer(SimpleImputer):
    """
    A weighted version of a SimpleImputer providing a 'fit' function with a weight parameter
    """

    def fit(self, X, y=None, sample_weight=None):
        """
        Fits the imputer with sample weights

        :param X: The data to fit, possibly containing NaNs
        :param y: Ignored
        :param sample_weight: Optionally specifies the sample weights for each sample in 'X'
        :raises ValueError: When the imputation strategy is unknown
        """
        X = getattr(X, "values", X)

        # This is required to force fit to work with 1D arrays
        if X.ndim == 1:
            X = X[:, np.newaxis]

        # Fit SimpleImputer
        self = super().fit(X, y)

        # No weights provided, just return fitted SimpleImputer
        if sample_weight is None:
            return self

        # Override SimpleImputer's strategies
        statistics = []
        for column_index in range(X.shape[1]):
            # find the impute value
            if self.strategy == "mean":
                value = nanaverage(X[:, column_index], weights=sample_weight)
            elif self.strategy == "most_frequent":
                value = weighted_mode(X[:, column_index], sample_weight)[0][0]
            elif self.strategy == "constant":
                value = self.fill_value
            else:
                raise ValueError(
                    "Invalid weighted imputation strategy: %s" % self.strategy
                )
            statistics.append(value)
        self.statistics_ = np.array(statistics)

        # train the indicator - here for completeness (at least a bit of it)
        if self.add_indicator:
            self.indicator_ = MissingIndicator(missing_values=self.missing_values)
            self.indicator_.fit(X)
        else:
            self.indicator_ = None

        return self

    def transform(self, X):
        """
        Transforms the input by imputing its missing values

        :param X: The original input to transform
        :return: The transformed input with the missing values imputed
        """
        X = getattr(X, "values", X)
        if X.ndim == 1:
            return super().transform(X[:, np.newaxis])[:, 0]
        return super().transform(X)

    def fit_transform(self, X, **kwargs):
        """Fit on the data, then transform."""
        return self.fit(X, **kwargs).transform(X)


class WeightedStandardScaler(StandardScaler):
    """
    A variant of the StandardScaler that uses sample weights
    """

    # pylint: disable=arguments-differ
    def fit(self, X, y=None, sample_weight=None):
        # pylint: disable=attribute-defined-outside-init
        """
        Fits the weighted standard scalar
        """
        X = getattr(X, "values", X)

        if sample_weight is None:
            return super().fit(X, y)

        sample_weight = getattr(sample_weight, "values", sample_weight)
        moment = 0
        if X.ndim == 2 and sample_weight.ndim == 2:
            # each column is weighted differently
            mean = np.average(X, axis=0, weights=sample_weight).flatten()
            std = (
                1.0
                if not self.with_std
                else np.sqrt(
                    np.sum(
                        (X - mean[np.newaxis]) ** 2
                        * np.reshape(sample_weight, X.shape),
                        axis=0,
                    )
                    / (sample_weight.sum(axis=0, keepdims=True) - moment)
                )
            )
        elif X.ndim == 2 and sample_weight.ndim == 1:
            # each column is weighted the same
            mean = np.average(X, axis=0, weights=sample_weight).flatten()

            # pylint: disable=unsubscriptable-object
            std = (
                1.0
                if not self.with_std
                else np.sqrt(
                    np.sum(
                        (X - mean[np.newaxis]) ** 2 * sample_weight[:, np.newaxis],
                        axis=0,
                    )
                    / (sample_weight.sum() - moment)
                )
            )
        elif X.ndim == 1 and (
            sample_weight.ndim == 1
            or (sample_weight.ndim == 2 and sample_weight.shape[-1] == 1)
        ):
            # there is only one column
            mean = np.average(X, axis=0, weights=sample_weight.flatten()).flatten()
            std = (
                1.0
                if not self.with_std
                else np.sqrt(
                    np.sum((X - mean) ** 2 * sample_weight.flatten(), axis=0)
                    / (sample_weight.sum() - moment)
                )
            )
        else:
            raise ValueError(
                "Unknown dimensionality combination for the columns and weights: column=%d, weights=%d"
                % (X.ndim, sample_weight.ndim)
            )

        if self.with_mean:
            self.mean_ = mean
        if self.with_std:
            self.scale_ = np.maximum(std, 1e-5)

        return self

    def transform(self, X, copy=None):
        """
        Transforms the data using the already-trained model
        """
        if isinstance(X, pd.DataFrame):
            result = super().transform(X, copy=copy)
            return pd.DataFrame(result, index=X.index, columns=X.columns)
        if X.ndim == 1:
            result = super().transform(X[:, np.newaxis], copy=copy).flatten()
        else:
            result = super().transform(X, copy=copy)
        return result


class RobustStandardScaler(RobustScaler):
    """
    A variant of the RobustScaler that instead of measuring the scale by the quantiles, scales like a normal
    distribution (by the mean and variance) but discards the extreme percentiles
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._is_empty = False

    def fit(self, X, y=None, sample_weight=None):
        """
        Fits the robust standard scaler
        :raises ValueError: When the quantile range is invalid
        """
        q_min, q_max = self.quantile_range
        if not 0 <= q_min <= q_max <= 100:
            raise ValueError("Invalid quantile range: %s" % str(self.quantile_range))

        X = getattr(X, "values", X)
        if sample_weight is not None:
            sample_weight = getattr(sample_weight, "values", sample_weight)

        if X.shape[0] == 0 or X.shape[1] == 0:
            self._is_empty = True
            self.center_ = None
            self.scale_ = None
            self.center_after_ = None
            self.scale_after_ = None
            return self

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)

            if sample_weight is not None:
                quantiles = nanquantile(X, self.quantile_range, sample_weight, axis=0)
            else:
                quantiles = np.nanpercentile(X, self.quantile_range, axis=0)

            if quantiles.ndim == 1:
                quantiles = np.stack([quantiles, quantiles], axis=0)
            indices = [
                list(
                    np.where(
                        np.logical_and(
                            quantiles[0, i] <= X[:, i], X[:, i] <= quantiles[1, i]
                        )
                    )[0]
                )
                for i in range(X.shape[1])
            ]
            values = [X[index, i] for i, index in enumerate(indices)]
            max_len = max(map(len, values))
            values = (
                np.zeros((1, X.shape[1]))
                if not values or not list(values[0])
                else np.stack(
                    [
                        list(row) + [np.mean(row)] * (max_len - len(row))
                        for row in values
                    ],
                    axis=1,
                )
            )
            if sample_weight is not None:
                subset_sample_weight = [sample_weight[index] for index in indices]
                subset_sample_weight = (
                    np.zeros((1, X.shape[1]))
                    if not subset_sample_weight or not list(subset_sample_weight[0])
                    else np.stack(
                        [
                            list(row) + [0.0] * (max_len - len(row))
                            for row in subset_sample_weight
                        ],
                        axis=1,
                    )
                )
            else:
                subset_sample_weight = None

        model = WeightedStandardScaler(
            copy=self.copy, with_mean=self.with_centering, with_std=self.with_scaling
        )
        model.fit(values, sample_weight=subset_sample_weight)

        if self.with_centering:
            self.center_ = model.mean_

        if self.with_scaling:
            self.scale_ = np.sqrt(model.scale_**2 + 1e-4)

        # now transform it again, so that after the robust log adjustment it has mean=0, stddev=1
        X = robust_log_adjust(super().transform(X))

        post_scale = WeightedStandardScaler(
            copy=self.copy, with_mean=self.with_centering, with_std=self.with_scaling
        )
        post_scale.fit(X, sample_weight=sample_weight)
        if self.with_centering:
            self.center_after_ = post_scale.mean_

        if self.with_scaling:
            self.scale_after_ = post_scale.scale_
            if isinstance(self.scale_after_, np.ndarray):
                self.scale_after_[self.scale_after_ == 0] = 1
            elif self.scale_after_ == 0:
                self.scale_after_ = 1

        return self

    def transform(self, X):
        """
        Transforms the data using the robust log adjustment so that mean=0, stddev=1
        """
        X = getattr(X, "values", X)

        if self._is_empty:
            return X  # the input was empty so we'll assume this was too

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            X = robust_log_adjust(super().transform(X))
            if self.with_centering:
                X -= np.expand_dims(self.center_after_, axis=0)
            if self.with_scaling:
                X /= np.expand_dims(self.scale_after_, axis=0)
            return X

    def inverse_transform(self, X):
        """
        Performs the inverse transformation
        """
        X = getattr(X, "values", X)

        if self._is_empty:
            return X  # the input was empty so we'll assume this was too

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            if hasattr(self, "scale_after_"):
                X = X * np.expand_dims(self.scale_after_, axis=0)
            if hasattr(self, "center_after_"):
                X = X + np.expand_dims(self.center_after_, axis=0)
            return super().inverse_transform(inv_robust_log_adjust(X))


class LabeledDataFrame(pd.DataFrame):
    """
    Represents a variant on a DataFrame that includes a `label` attribute to be used in sequence labeling tasks. Note
    that this attribute will not be serialized like the other traditional DataFrame attributes and data.
    """

    def __init__(self, *args, label=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.label = label

    @classmethod
    def from_full_dataframe(cls, full_dataframe: pd.DataFrame, label_column: str):
        """
        Extracts a column from the DataFrame to use as the label for a new LabeledDataFrame

        :param full_dataframe: The DataFrame, including a constant column containing the sequence's label
        :param label_column: The name of the column containing the labels. This must be present in `full_dataframe` and
            have only one unique value.
        :return: The new LabeledDataFrame, with the label attribute set and the label column removed
        """
        if full_dataframe.shape[0] == 0:
            raise ValueError(
                "The DataFrame is empty, so its label could not be inferred"
            )
        if label_column not in full_dataframe.columns:
            raise ValueError(
                f"The column '{label_column}' is not present in the DataFrame"
            )
        values = set(full_dataframe[label_column].values)
        if len(values) != 1:
            raise ValueError(
                f"Multiple values were found in '{label_column}': {values}"
            )
        return cls(
            full_dataframe[
                [column for column in full_dataframe.columns if column != label_column]
            ],
            label=list(values)[0],
        )


class repeatable_map:
    """
    Similar to the built-in map() class except this iterator can be repeated
    """

    def __init__(self, function, iterable):
        self.function = function
        self.iterable = iterable

    def __iter__(self):
        return map(self.function, self.iterable)

    def __len__(self):
        return len(self.iterable)

    def __getitem__(self, item):
        return self.function(self.iterable[item])
