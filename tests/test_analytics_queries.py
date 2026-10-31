"""Tests for reusable analytic query/aggregation builders."""

from parseus.analytics.queries import (
    CONN_DATASET_QUERY,
    histogram_cardinality_agg,
)


def test_conn_dataset_query_constant():
    assert CONN_DATASET_QUERY == {"term": {"event.dataset": "conn"}}


def test_histogram_cardinality_agg_shape():
    agg = histogram_cardinality_agg(
        term_field="source.ip",
        term_label="source_ips",
        metric_field="destination.ip",
        metric_label="destination_ips",
    )
    assert agg == {
        "aggs": {
            "composite": {
                "composite": {
                    "size": 10000,
                    "sources": [
                        {
                            "timestamp": {
                                "date_histogram": {
                                    "field": "@timestamp",
                                    "calendar_interval": "minute",
                                }
                            }
                        },
                        {"source_ips": {"terms": {"field": "source.ip"}}},
                    ],
                },
                "aggs": {
                    "destination_ips": {"cardinality": {"field": "destination.ip"}}
                },
            }
        }
    }


def test_histogram_cardinality_agg_honors_interval_and_size():
    agg = histogram_cardinality_agg(
        term_field="destination.ip",
        term_label="dest_ips",
        metric_field="destination.port",
        metric_label="destination_ports",
        calendar_interval="hour",
        size=500,
    )
    composite = agg["aggs"]["composite"]["composite"]
    assert composite["size"] == 500
    histogram = composite["sources"][0]["timestamp"]["date_histogram"]
    assert histogram["calendar_interval"] == "hour"
