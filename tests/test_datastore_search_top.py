"""Unit tests for :meth:`parseus.datastore.client.DataStore.search_top`.

``search_top`` backs the alerts page's frequently polled query. These pin that it
answers a missing index with the search itself (no separate ``index_exists``
round trip, which also removes a check-then-search race), and keep its existing
guarantees: an honest total and no silently truncated pages.
"""

import pytest

from parseus.datastore.client import DatastoreShardFailure, DataStore


@pytest.fixture(params=["elasticsearch", "opensearch"])
def store(request):
    """A real DataStore of each flavour. Constructing one does not connect."""
    return DataStore("http://localhost:1", base=request.param)


def _hits(documents, total):
    return {
        "_shards": {"total": 1, "failed": 0},
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": [{"_source": doc} for doc in documents],
        },
    }


def _stub_search(monkeypatch, store, response):
    calls = []

    def fake_search(**kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(store, "search", fake_search)
    return calls


def test_returns_documents_and_true_total(monkeypatch, store):
    calls = _stub_search(monkeypatch, store, _hits([{"a": 1}, {"a": 2}], total=4718))

    documents, total = store.search_top("alerts-*", size=2)

    assert documents == [{"a": 1}, {"a": 2}]
    assert total == 4718
    assert calls[0]["body"]["size"] == 2
    assert calls[0]["body"]["track_total_hits"] is True


def test_missing_index_is_handled_by_the_search_not_a_second_request(monkeypatch, store):
    """No ``index_exists`` call; the search itself must tolerate absent indices."""

    def forbidden(*args, **kwargs):
        raise AssertionError("search_top must not make a separate existence request")

    monkeypatch.setattr(store, "index_exists", forbidden)
    calls = _stub_search(monkeypatch, store, _hits([], total=0))

    documents, total = store.search_top("alerts-*")

    assert (documents, total) == ([], 0)
    assert calls[0]["ignore_unavailable"] is True
    assert calls[0]["allow_no_indices"] is True


def test_shard_failure_raises_instead_of_returning_a_short_page(monkeypatch, store):
    response = _hits([{"a": 1}], total=1)
    response["_shards"] = {
        "total": 2,
        "failed": 1,
        "failures": [{"reason": {"type": "script_exception"}}],
    }
    _stub_search(monkeypatch, store, response)

    with pytest.raises(DatastoreShardFailure):
        store.search_top("alerts-*")


def test_error_body_raises(monkeypatch, store):
    _stub_search(monkeypatch, store, {"error": "boom"})

    with pytest.raises(DatastoreShardFailure):
        store.search_top("alerts-*")


def test_sort_and_source_restriction_are_forwarded(monkeypatch, store):
    calls = _stub_search(monkeypatch, store, _hits([], total=0))

    store.search_top(
        "alerts-*",
        query={"term": {"handled": False}},
        sort=[{"@timestamp": "desc"}],
        return_fields=["event"],
    )

    body = calls[0]["body"]
    assert body["query"] == {"term": {"handled": False}}
    assert body["sort"] == [{"@timestamp": "desc"}]
    assert body["_source"] == ["event"]
