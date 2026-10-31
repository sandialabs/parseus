"""Reusable datastore filter builders for analytic descriptors.

These construct the Elasticsearch/OpenSearch ``filter`` fragments that several
analytics share, so decorators declare intent (e.g. "match private source IPs")
instead of repeating verbose nested bool/should blocks.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: RFC 1918 private IPv4 ranges.
PRIVATE_IPV4_CIDRS = ("10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12")


def private_ip_filter(*fields: str) -> List[Dict[str, Any]]:
    """Return a filter matching any private-range IP on each given field.

    One ``bool``/``should`` clause is produced per field, each requiring the
    field to fall in one of :data:`PRIVATE_IPV4_CIDRS`. Passing multiple fields
    (e.g. ``"source.ip"``, ``"destination.ip"``) yields one clause each, which
    combine as an AND across fields — matching the previous inline filters.

    :param fields: Document field names to constrain to private IP ranges.
    :return: A list of filter clauses suitable for an ``*_idx`` ``filter`` value.
    """
    return [
        {
            "bool": {
                "minimum_should_match": 1,
                "should": [
                    {"match_phrase": {field: cidr}} for cidr in PRIVATE_IPV4_CIDRS
                ],
            }
        }
        for field in fields
    ]
