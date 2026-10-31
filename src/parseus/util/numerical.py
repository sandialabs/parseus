"""
Utilities for normalizing data.
"""

from typing import Union

import numpy as np
import pandas as pd
from sklearn import preprocessing


def robust_log_adjust(
    array,
    log_threshold=10.0,
    log_base=np.e,
):
    """
    Processes rescaled input and robustly rescales it using logarithm for large values

    :param np.ndarray array: The input array
    :param float log_threshold: The threshold for the magnitude of the value to start
                                using logarithms
    :param float log_base: The base of the logarithm to be used. Using log_base=np.e
                           results in a smooth function
    :return: The robustly rescaled and adjusted array
    """
    abs_scaled = np.abs(array)
    base_scaled = np.clip(abs_scaled, 0, log_threshold)
    post_log = np.log((np.clip(abs_scaled - log_threshold, 0, None) + 1)) / np.log(
        log_base
    )
    return np.sign(array) * (base_scaled + post_log)


def inv_robust_log_adjust(
    array: Union[float, int, np.ndarray],
    log_threshold: float = 10.0,
    log_base: float = np.e,
):
    """
    Inverts the results of :func:`robust_log_adjust`

    :param np.ndarray array: The robustly rescaled and adjusted array
    :param float log_threshold: The threshold for the magnitude that the value started using logarithms
    :param float log_base: The base of the logarithm that was used
    :return: The original input array
    """
    abs_scaled = np.abs(array)
    base_scaled = np.clip(abs_scaled, 0, log_threshold)
    post_log = np.clip(abs_scaled - log_threshold, 0, None)
    post_exp = np.exp(np.log(log_base) * post_log) - 1
    return np.sign(array) * (base_scaled + post_exp)


def nanaverage(data: np.ndarray, axis=None, weights=None, **kwargs) -> np.ndarray:
    if hasattr(data, "values"):
        data = data.values
    if hasattr(weights, "values"):
        weights = weights.values

    if weights is None:
        return np.nanmean(data, axis=axis, **kwargs)

    # broadcast the weights to the same size as the original and fill in
    # NaNs where the data is NaN
    if axis is not None:
        new_weights_shape = [1] * data.ndim
        new_weights_shape[axis] = weights.size
        weights = np.reshape(weights, new_weights_shape)
    weights = np.broadcast_to(weights, data.shape) + 0 * data

    keep_dims = kwargs.pop("keepdims", False)
    weighted_sum = np.nansum(data * weights, axis=axis, **kwargs)
    result = weighted_sum / np.nansum(weights, axis=axis)
    if keep_dims:
        result = np.expand_dims(result, axis=axis)
    return result


def normalize(dataframe):
    """
    Takes a data frame and scales all of its elements between 0-1
    Returns scaled dataframe
    """
    if dataframe.empty:
        return dataframe
    values = dataframe.values  # returns a numpy array
    if not isinstance(values[0], np.ndarray):
        values = values.reshape(-1, 1)
    min_max_scaler = preprocessing.MinMaxScaler()
    values_scaled = min_max_scaler.fit_transform(values)
    return pd.DataFrame(values_scaled, columns=dataframe.columns, index=dataframe.index)
