"""Reusable datastore query and aggregation builders for analytic descriptors.

Keeps verbose Elasticsearch/OpenSearch query and composite-aggregation literals
out of the analytic decorators and ``__init__`` methods, so several analytics can
share one definition instead of repeating large nested dicts.
"""

from __future__ import annotations

from typing import Any, Dict

#: The ``conn`` dataset term query shared by the network-anomaly analytics.
CONN_DATASET_QUERY: Dict[str, Any] = {"term": {"event.dataset": "conn"}}


def histogram_cardinality_agg(
    *,
    term_field: str,
    term_label: str,
    metric_field: str,
    metric_label: str,
    calendar_interval: str = "minute",
    size: int = 10000,
) -> Dict[str, Any]:
    """Build a composite aggregation of (time-bucket x term) -> cardinality.

    Produces the shape several network analytics share: a ``date_histogram`` on
    ``@timestamp`` plus a ``terms`` source, with a ``cardinality`` metric.

    :param term_field: Field for the ``terms`` composite source (e.g. ``source.ip``).
    :param term_label: Name for that source bucket (e.g. ``source_ips``).
    :param metric_field: Field for the ``cardinality`` metric (e.g. ``destination.ip``).
    :param metric_label: Name for the metric aggregation (e.g. ``destination_ips``).
    :param calendar_interval: ``date_histogram`` interval (default ``"minute"``).
    :param size: Composite aggregation page size.
    :return: The composite-aggregation dict for an ``IndexQuery.composite_agg``.
    """
    return {
        "aggs": {
            "composite": {
                "composite": {
                    "size": size,
                    "sources": [
                        {
                            "timestamp": {
                                "date_histogram": {
                                    "field": "@timestamp",
                                    "calendar_interval": calendar_interval,
                                }
                            }
                        },
                        {term_label: {"terms": {"field": term_field}}},
                    ],
                },
                "aggs": {
                    metric_label: {"cardinality": {"field": metric_field}}
                },
            }
        }
    }
