"""Aggregation-backed DSData must treat a missing index as "no data".

``DataStore.get_aggs`` returns ``None`` when the index does not exist. DSData
used to call ``.get`` on that result, so training a supervised analytic before
any data had been ingested failed with
``'NoneType' object has no attribute 'get'`` instead of fitting on nothing.
"""

import logging

import pytest

from parseus.analytics.network_anomalies.excessive_conversation_analytic import (
    ExcessiveConversationAnalytic,
    _conversation_agg,
)
from parseus.datastore.data import DSData


class _MissingIndexHost:
    """Mimics DataStore.get_aggs for an index that does not exist."""

    def get_aggs(self, index, aggs, query=None):
        return None


class _EmptyIndexHost:
    """Mimics an existing index with no matching buckets."""

    def get_aggs(self, index, aggs, query=None):
        name = next(iter(aggs))
        return {"aggregations": {name: {"buckets": []}}}


@pytest.mark.parametrize("host", [_MissingIndexHost(), _EmptyIndexHost()])
def test_composite_agg_without_data_yields_no_buckets(host):
    data = DSData(host, "packets-*", composite_agg=_conversation_agg())
    assert list(data) == []
    assert not data


def test_plain_agg_on_missing_index_yields_empty_result():
    data = DSData(_MissingIndexHost(), "packets-*", aggs={"a": {"avg": {}}})
    assert list(data) == [{}]


@pytest.mark.parametrize("host", [_MissingIndexHost(), _EmptyIndexHost()])
def test_excessive_conversation_trains_on_no_data(host):
    analytic = ExcessiveConversationAnalytic(log=logging.getLogger("test"))
    analytic.fit(DSData(host, "packets-*", composite_agg=_conversation_agg()))

    assert analytic.get_fit_results().empty
    # The fitted (empty) model must still be serialisable so it can be saved.
    assert "convo_counts_" in analytic.state_dict()
