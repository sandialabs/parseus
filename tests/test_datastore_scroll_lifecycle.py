"""Unit tests for :class:`parseus.datastore.data.DSData` scroll-context lifecycle.

These pin down a dormant durability bug: querying result sets through
:class:`DSData` (as the alerts page does on every refresh/poll) opens an
Elasticsearch/OpenSearch scroll context via ``start_scroll``/``continue_scroll``
but historically never called ``clear_scroll``. Each query left its scroll
context open on the datastore for the full ``SCROLL_TIMEOUT_SECONDS`` TTL, so
sustained or concurrent polling (e.g. several operators with the alerts page
open, or the SSE/fallback poll loop) could exhaust the datastore's
``search.max_open_scroll_context`` limit and start failing every subsequent
query with a "too many scroll contexts" error -- surfaced to the browser as an
axios failure on ``alert-query/``/``alert-stream/``.

A fake, in-memory host simulates the ES/OpenSearch scroll API (including
heavy/long-term, high-volume and concurrent use) without needing a live
datastore, so these tests run as plain unit tests.
"""

from __future__ import annotations

import uuid

import pytest

from parseus.datastore.data import DSData


class FakeScrollHost:
    """In-memory stand-in for the ES/OpenSearch scroll API used by DSData.

    Tracks every scroll id that has been opened and not yet cleared, so tests
    can assert on how many scroll contexts are left dangling -- the thing a
    real datastore would eventually reject once it hits
    ``search.max_open_scroll_context``.
    """

    #: Matches Elasticsearch/OpenSearch's default open-scroll-context ceiling.
    MAX_OPEN_SCROLL_CONTEXTS = 500

    def __init__(self, documents, page_size=2):
        self._documents = list(documents)
        self._page_size = page_size
        self.open_scrolls: dict[str, int] = {}
        self.start_scroll_calls = 0
        self.continue_scroll_calls = 0
        self.clear_scroll_calls = 0

    def _new_scroll_id(self) -> str:
        return str(uuid.uuid4())

    def _check_capacity(self) -> None:
        if len(self.open_scrolls) >= self.MAX_OPEN_SCROLL_CONTEXTS:
            raise RuntimeError(
                "Trying to create too many scroll contexts. Must be less than or "
                f"equal to: [{self.MAX_OPEN_SCROLL_CONTEXTS}]"
            )

    def start_scroll(self, index, size=10000, timeout="5m", query=None, sort=None, return_fields=None):
        self.start_scroll_calls += 1
        self._check_capacity()
        scroll_id = self._new_scroll_id()
        self.open_scrolls[scroll_id] = 0
        return self.continue_scroll(scroll_id, timeout=timeout, _is_initial=True)

    def continue_scroll(self, scroll_id, timeout="5m", _is_initial=False):
        if not _is_initial:
            self.continue_scroll_calls += 1
        if scroll_id not in self.open_scrolls:
            # expired/cleared scroll -- real hosts error; DSData treats a
            # None scroll id as "no more data".
            return None, []
        offset = self.open_scrolls[scroll_id]
        page = self._documents[offset : offset + self._page_size]
        self.open_scrolls[scroll_id] = offset + len(page)
        # Matches DataStore.start_scroll/continue_scroll: already-unwrapped
        # `_source` dicts (flat, with "@timestamp" at the top level), not
        # `{"_source": doc}`-wrapped hits.
        return scroll_id, list(page)

    def clear_scroll(self, scroll_id):
        self.clear_scroll_calls += 1
        self.open_scrolls.pop(scroll_id, None)
        return {"succeeded": True, "num_freed": 1}


def _make_docs(count):
    return [{"@timestamp": f"2024-01-01T00:00:{i:02d}.000Z", "n": i} for i in range(count)]


# ---------------------------------------------------------------------------
# Core leak-fix behaviour.
# ---------------------------------------------------------------------------


def test_exhausting_a_query_clears_its_scroll():
    """Fully iterating a small result set must not leave a scroll context open."""
    host = FakeScrollHost(_make_docs(5), page_size=2)
    data = DSData(host, "alerts-*", query={"match_all": {}})

    results = list(data)

    assert len(results) == 5
    assert host.open_scrolls == {}, "scroll context was not released after exhaustion"
    assert host.clear_scroll_calls >= 1


def test_explicit_close_clears_an_in_progress_scroll():
    """A caller that stops partway through a result set can still release it."""
    host = FakeScrollHost(_make_docs(50), page_size=5)
    data = DSData(host, "alerts-*", query={"match_all": {}})

    # Only look at the first page; never exhaust the scroll.
    first_doc = data[0]
    assert first_doc["n"] == 0
    assert host.open_scrolls, "expected an open scroll before close()"

    data.close()

    assert host.open_scrolls == {}


def test_context_manager_clears_scroll_on_exit():
    host = FakeScrollHost(_make_docs(50), page_size=5)

    with DSData(host, "alerts-*", query={"match_all": {}}) as data:
        _ = data[0]
        assert host.open_scrolls

    assert host.open_scrolls == {}


def test_empty_result_set_does_not_leak_a_scroll():
    host = FakeScrollHost([], page_size=5)
    data = DSData(host, "alerts-*", query={"match_all": {}})

    assert list(data) == []
    assert host.open_scrolls == {}


# ---------------------------------------------------------------------------
# Heavy / long-term use: repeated polling must not accumulate open scrolls.
# ---------------------------------------------------------------------------


def test_repeated_polling_never_accumulates_open_scrolls():
    """Simulate the alerts page's poll loop querying hundreds of times in a row.

    Before the fix, each refresh opened a scroll that was only ever released
    by the datastore's own TTL expiry; back-to-back polling (as happens on
    every SSE tick or fallback-interval refresh) would accumulate open scroll
    contexts far faster than they expired.
    """
    host = FakeScrollHost(_make_docs(3), page_size=10)

    for _ in range(1000):
        data = DSData(host, "alerts-*", query={"term": {"handled": False}})
        results = list(data)
        assert len(results) == 3
        # Each poll's scroll must already be gone -- no accumulation.
        assert host.open_scrolls == {}

    assert host.clear_scroll_calls >= 1000


def test_many_concurrent_unfinished_queries_stay_under_the_open_scroll_ceiling():
    """Many simultaneously open (but unfinished) queries must remain closeable.

    This does not assert that DSData enforces a cap by itself (MAX_SCROLLS
    bounds a single object's *own* concurrent scrolls) -- it asserts that each
    independent query object can always release what it opened, so an
    operator-facing cleanup path (page unload, request teardown, timeout) can
    always bring the datastore back under its scroll-context ceiling instead
    of accumulating leaked contexts indefinitely.
    """
    host = FakeScrollHost(_make_docs(100), page_size=5)
    sessions = []

    # Open many separate queries (e.g. many browser tabs/users polling the
    # alerts page) and pull one page from each, without exhausting any of them.
    for _ in range(50):
        data = DSData(host, "alerts-*", query={"match_all": {}})
        _ = data[0]
        sessions.append(data)

    assert len(host.open_scrolls) == 50
    assert len(host.open_scrolls) < host.MAX_OPEN_SCROLL_CONTEXTS

    for data in sessions:
        data.close()

    assert host.open_scrolls == {}


def test_closing_twice_is_safe_and_idempotent():
    host = FakeScrollHost(_make_docs(10), page_size=2)
    data = DSData(host, "alerts-*", query={"match_all": {}})
    _ = data[0]

    data.close()
    data.close()  # must not raise, must not double-clear incorrectly

    assert host.open_scrolls == {}


def test_cleanup_failure_during_close_does_not_raise():
    """A clear_scroll failure (e.g. already-expired scroll) must not propagate.

    Cleanup is best-effort: the scroll may have already timed out server-side,
    and a transient cleanup error must never fail the caller's request.
    """

    class FlakyHost(FakeScrollHost):
        def clear_scroll(self, scroll_id):
            raise ConnectionError("simulated transient datastore failure")

    host = FlakyHost(_make_docs(10), page_size=2)
    data = DSData(host, "alerts-*", query={"match_all": {}})
    _ = data[0]

    data.close()  # must not raise despite clear_scroll failing


def test_expired_scroll_is_proactively_cleared_before_its_ttl():
    """Scrolls pruned for being near expiry must be cleared, not just forgotten."""
    host = FakeScrollHost(_make_docs(50), page_size=5)
    data = DSData(host, "alerts-*", query={"match_all": {}})
    _ = data[0]

    (scroll,) = data._scrolls
    # Pretend this scroll's bookkeeping is already past its TTL.
    import datetime as dt

    scroll.last_time_accessed = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
        seconds=DSData.SCROLL_TIMEOUT_SECONDS + 1
    )

    data._prune_expired_scrolls()

    assert host.open_scrolls == {}
    assert data._scrolls == []


# ---------------------------------------------------------------------------
# Regression guard: a datastore nearing capacity still degrades gracefully.
# ---------------------------------------------------------------------------


def test_queries_keep_succeeding_once_scrolls_are_released_under_pressure():
    """End-to-end durability check against the fake host's open-scroll ceiling.

    Drives far more sequential queries than the host's scroll-context ceiling
    would allow if contexts were not released between queries, proving the
    fixed lifecycle keeps the alerts-page refresh loop durable under
    long-term/heavy use.
    """
    host = FakeScrollHost(_make_docs(4), page_size=2)
    ceiling = host.MAX_OPEN_SCROLL_CONTEXTS

    for i in range(ceiling * 3):
        data = DSData(host, "alerts-*", query={"term": {"handled": False}})
        try:
            results = list(data)
        except RuntimeError as err:  # pragma: no cover - failure path for debugging
            pytest.fail(f"query {i} hit the scroll-context ceiling: {err}")
        assert len(results) == 4

    assert host.open_scrolls == {}
