"""Integration tests for DataStore against a live Elasticsearch/OpenSearch host.

Requires a reachable datastore at DATASTORE_HOST_URL (defaults to
http://localhost:9200). See tests/globals.py for connection configuration.
"""

import json
from datetime import datetime, timezone
from os import environ
from time import sleep

import elasticsearch
import pytest

from parseus.datastore.client import DataStore
from parseus.util.datetime_utils import make_zulu_time

from .globals import DATASTORE, DATASTORE_HOST_URL

TEMP_INDEX = "test-temp"


@pytest.fixture(scope="module")
def _temp_index():
    """Create TEMP_INDEX once for this module's tests, then delete it."""
    host = DATASTORE
    host.create_index(TEMP_INDEX)
    yield
    DATASTORE.delete_index(TEMP_INDEX)


def test_inactive_host(_temp_index):
    host = DataStore("http://localhost:9199/")
    assert not host.create_index("test")


def test_end_to_end(_temp_index):
    # create the host and delete any old data
    host = DATASTORE
    host.clear_index(TEMP_INDEX)

    # make sure it's empty
    assert host.get_document_count(TEMP_INDEX) == 0

    # create it and fill it
    host.create_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [{"@timestamp": make_zulu_time(datetime.utcnow()), "hi": "test"}],
    )
    host.wait_for_documents(TEMP_INDEX, 4)
    assert host.get_document_count(TEMP_INDEX) == 1

    # test the re-index functionality
    host.delete_index(TEMP_INDEX + "2")
    host.create_index(TEMP_INDEX + "2")
    host.reindex(TEMP_INDEX, TEMP_INDEX + "2")
    host.wait_for_documents(TEMP_INDEX + "2", 4)
    assert host.get_document_count(TEMP_INDEX + "2") == 1
    host.delete_index(TEMP_INDEX + "2")

    # make sure we can clear it
    host.clear_index(TEMP_INDEX)
    sleep(1)  # let it clear everything
    assert host.get_document_count(TEMP_INDEX) == 0

    # make sure it gets deleted
    host.clear_index(TEMP_INDEX)
    assert host.get_document_count(TEMP_INDEX) == 0


def test_timestamps(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "hi": "test"},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "hi": "test"},
            {"@timestamp": "2020-01-01T02:00:00.000Z", "hi": "test"},
        ],
    )
    host.wait_for_documents(TEMP_INDEX, 4, min_documents=3)
    assert host.get_min_timestamp(TEMP_INDEX) == datetime(
        2020, 1, 1, 0, tzinfo=timezone.utc
    )
    assert host.get_max_timestamp(TEMP_INDEX) == datetime(
        2020, 1, 1, 2, tzinfo=timezone.utc
    )


def test_doc_count(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "hi": "test1"},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "hi": "test2"},
        ],
    )
    count = host.get_document_count(TEMP_INDEX)
    assert count == 2

    query = {"term": {"hi": "test2"}}
    count = host.get_document_count(TEMP_INDEX, query=query)
    assert count == 1


def test_time_range_query(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "hi": "test"},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "hi": "test"},
            {"@timestamp": "2020-01-01T02:00:00.000Z", "hi": "test"},
        ],
    )
    host.wait_for_documents(TEMP_INDEX, 4, min_documents=3)

    results = host.get_time_range_entries(TEMP_INDEX)
    assert len(list(results)) == 3

    results = host.get_time_range_entries(
        TEMP_INDEX, datetime(2020, 1, 1), datetime(2020, 1, 1, 1, 30, 0)
    )
    assert len(list(results)) == 2

    results = host.get_time_range_entries(
        TEMP_INDEX, datetime(2020, 1, 1, 0, 30, 0), datetime(2020, 1, 1, 1, 30, 0)
    )
    assert len(list(results)) == 1

    results = host.get_time_range_entries(
        TEMP_INDEX, datetime(2020, 1, 1, 0, 30, 0), datetime(2020, 1, 1, 2, 30, 0)
    )
    assert len(list(results)) == 2


def test_delete_by_query(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "hi": "test1"},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "hi": "test2"},
        ],
    )
    host.wait_for_documents(TEMP_INDEX, 4, min_documents=2)

    host.delete_by_query(TEMP_INDEX, {"term": {"hi": {"value": "test1"}}})
    sleep(1)
    assert host.get_document_count(TEMP_INDEX) == 1

    host.delete_by_query(TEMP_INDEX, [{"term": {"hi": {"value": "test2"}}}])
    sleep(1)
    assert host.get_document_count(TEMP_INDEX) == 0


def test_delete_by_query_multiple(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {
                "@timestamp": "2020-01-01T00:00:00.000Z",
                "hi": "test",
                "next": "test2",
            },
            {
                "@timestamp": "2020-01-01T01:00:00.000Z",
                "hi": "test",
                "next": "test2",
            },
        ],
    )
    host.wait_for_documents(TEMP_INDEX, min_documents=2)
    host.delete_by_query(
        TEMP_INDEX,
        [
            {"term": {"hi": {"value": "test"}}},
            {"term": {"next": {"value": "test2"}}},
        ],
    )
    assert host.get_document_count(TEMP_INDEX) == 0


def test_environment_invariant(_temp_index):
    host = DATASTORE

    # test that it works directly
    result = host.get_document_count("fake-index")

    # adjust the proxy environment variables and try again with a new host
    old = dict(environ)
    environ.update(
        {
            "http_proxy": "fakeproxy",
            "https_proxy": "fakeproxy",
            "no_proxy": "",
            "HTTP_PROXY": "fakeproxy",
            "HTTPS_PROXY": "fakeproxy",
            "NO_PROXY": "",
        }
    )
    try:
        host = DATASTORE
        assert host.get_document_count("fake-index") == result
    finally:
        environ.update(old)


def test_wait_for_documents(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)

    with pytest.raises(ValueError):
        DATASTORE.wait_for_documents("will-never-exist")

    with pytest.raises(TimeoutError):
        DATASTORE.wait_for_documents(TEMP_INDEX, max_seconds=1)

    host.bulk_push_docs(
        TEMP_INDEX, [{"@timestamp": "2020-01-01T00:00:00.000Z", "hi": "test"}]
    )
    host.wait_for_documents(TEMP_INDEX, min_documents=1)


def test_delete_fake_index(_temp_index):
    host = DATASTORE
    assert not host.delete_by_query(
        "does-not-exist", {"term": {"hi": {"value": "test1"}}}
    )


def test_pull_fake_index(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    assert list(host.get_all_entries(TEMP_INDEX)) == []


def test_min_timestamp_fake_index(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    assert host.get_min_timestamp(TEMP_INDEX).year == 1970


def test_max_timestamp_fake_index(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    assert host.get_max_timestamp(TEMP_INDEX).year == datetime.now().year


def test_scroll(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "hi": "test1"},
            {"@timestamp": "2020-01-01T00:00:01.000Z", "hi": "test2"},
            {"@timestamp": "2020-01-01T00:00:02.000Z", "hi": "test3"},
        ],
    )
    host.wait_for_documents(TEMP_INDEX, min_documents=3)
    scroll_id, docs = host.start_scroll(TEMP_INDEX, size=2, timeout="1m")
    new_scroll_id, new_docs = host.continue_scroll(scroll_id, timeout="1m")
    last_scroll_id, last_docs = host.continue_scroll(scroll_id, timeout="1m")
    assert scroll_id == new_scroll_id
    assert last_scroll_id is None
    assert (
        len(frozenset(map(lambda x: json.dumps(x, sort_keys=True), docs + new_docs)))
        == 3
    )
    assert not last_docs


def test_single_agg(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "score": 10},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "score": 20},
        ],
    )

    # Bucket agg
    bucket_agg = {
        "score_range": {
            "range": {
                "field": "score",
                "ranges": [{"from": 0.0, "to": 15.0}, {"from": 15.0}],
            }
        }
    }
    results = (
        host.get_aggs(TEMP_INDEX, aggs=bucket_agg)
        .get("aggregations", {})
        .get("score_range", {})
        .get("buckets", [])
    )
    for bucket in results:
        assert bucket.get("doc_count", None) == 1

    # Metric agg
    metric_agg = {"score_sum": {"sum": {"field": "score"}}}
    result = (
        host.get_aggs(TEMP_INDEX, aggs=metric_agg)
        .get("aggregations", {})
        .get("score_sum", {})
        .get("value", None)
    )
    assert result == 30.0

    if isinstance(host, elasticsearch.Elasticsearch):
        # Pipeline agg - parent
        agg = {
            "parent_agg": {
                "date_histogram": {
                    "field": "@timestamp",
                    "calendar_interval": "hour",
                },
                "aggs": {
                    **metric_agg,
                    "score_fraction": {
                        "normalize": {
                            "buckets_path": "score_sum",
                            "method": "percent_of_sum",
                            "format": "00.00%",
                        }
                    },
                },
            }
        }
        buckets = (
            host.get_aggs(TEMP_INDEX, aggs=agg)
            .get("aggregations", {})
            .get("parent_agg", {})
            .get("buckets", [])
        )
        assert (
            buckets[0].get("score_fraction", {}).get("value", None)
            == 0.3333333333333333
        )
        assert (
            buckets[1].get("score_fraction", {}).get("value", None)
            == 0.6666666666666666
        )

    # Pipeline agg - sibling
    agg = {
        "sibling_agg": {
            "date_histogram": {"field": "@timestamp", "calendar_interval": "hour"},
            "aggs": {**metric_agg},
        },
        "score_avg": {"avg_bucket": {"buckets_path": "sibling_agg>score_sum"}},
    }
    result = (
        host.get_aggs(TEMP_INDEX, aggs=agg)
        .get("aggregations", {})
        .get("score_avg", {})
        .get("value", None)
    )
    assert result == 15.0


def test_multiple_aggs(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "score": 10},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "score": 20},
        ],
    )

    # Pass aggs as a list
    aggs = [
        {"score_max": {"max": {"field": "score"}}},
        {"score_sum": {"sum": {"field": "score"}}},
    ]
    result = host.get_aggs(TEMP_INDEX, aggs=aggs)
    assert result["aggregations"]["score_max"]["value"] == 20.0
    assert result["aggregations"]["score_sum"]["value"] == 30.0


def test_composite_agg(_temp_index):
    host = DATASTORE
    host.clear_index(TEMP_INDEX)
    host.bulk_push_docs(
        TEMP_INDEX,
        [
            {"@timestamp": "2020-01-01T00:00:00.000Z", "score": 10, "risky": False},
            {"@timestamp": "2020-01-01T01:00:00.000Z", "score": 20, "risky": True},
        ],
    )
    composite_agg = {
        "buckets": {
            "composite": {
                "sources": [
                    {"rank": {"terms": {"field": "score"}}},
                    {"suspicious": {"terms": {"field": "risky"}}},
                ]
            }
        }
    }
    result = (
        host.get_aggs(TEMP_INDEX, aggs=composite_agg)
        .get("aggregations", {})
        .get("buckets", {})
    )

    # Verify that an after_key is returned
    assert result["after_key"] == {"rank": 20, "suspicious": True}

    # Verify the composite agg results
    assert result["buckets"][0]["key"] == {"rank": 10, "suspicious": False}
    assert result["buckets"][1]["key"] == {"rank": 20, "suspicious": True}


def test_standard_url():
    env_host = environ.get("DATASTORE_HOST_URL", DATASTORE_HOST_URL)
    host1 = DataStore(env_host)
    host2 = DATASTORE
    assert host1.url == host2.url


def test_username_pass_url():
    host1 = DataStore("https://test-user:test-password@localhost:9201")
    host2 = DataStore(
        "https://localhost:9201", username="test-user", password="test-password"
    )
    assert host1.url == host2.url
