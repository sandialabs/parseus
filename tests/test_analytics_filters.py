"""Tests for reusable analytic filter builders."""

from parseus.analytics.filters import PRIVATE_IPV4_CIDRS, private_ip_filter


def _expected_clause(field):
    return {
        "bool": {
            "minimum_should_match": 1,
            "should": [{"match_phrase": {field: cidr}} for cidr in PRIVATE_IPV4_CIDRS],
        }
    }


def test_private_ip_filter_single_field():
    assert private_ip_filter("source.ip") == [_expected_clause("source.ip")]


def test_private_ip_filter_multiple_fields_one_clause_each():
    result = private_ip_filter("source.ip", "destination.ip")
    assert result == [
        _expected_clause("source.ip"),
        _expected_clause("destination.ip"),
    ]


def test_private_ip_filter_no_fields_is_empty():
    assert private_ip_filter() == []


def test_uses_rfc1918_ranges():
    assert PRIVATE_IPV4_CIDRS == ("10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12")
