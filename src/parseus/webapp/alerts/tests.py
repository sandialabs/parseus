import asyncio
import json
import threading
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from . import views


class AlertViewValidationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post_json(self, view, payload):
        request = self.factory.post(
            "/alerts/test/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return view(request)

    def test_alert_query_rejects_invalid_method(self):
        request = self.factory.get("/alerts/alert-query/")
        response = views.alert_query(request)

        self.assertEqual(response.status_code, 405)

    def test_alert_query_rejects_invalid_alert_type(self):
        response = self.post_json(views.alert_query, {"alert_type": "unknown"})

        self.assertEqual(response.status_code, 400)

    def test_handle_alerts_rejects_invalid_handle_type(self):
        response = self.post_json(
            views.handle_alerts,
            {"handle_type": "ignored", "uuids": ["alert-1"]},
        )

        self.assertEqual(response.status_code, 400)

    def test_handle_alerts_rejects_invalid_uuid_payload(self):
        response = self.post_json(
            views.handle_alerts,
            {"handle_type": "flagged", "uuids": "alert-1"},
        )

        self.assertEqual(response.status_code, 400)

    def test_handle_alerts_accepts_empty_selection_without_datastore(self):
        response = self.post_json(
            views.handle_alerts,
            {"handle_type": "flagged", "uuids": []},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("No alerts selected", response.content.decode())

    def test_clear_all_rejects_invalid_alert_type(self):
        response = self.post_json(views.clear_all_data, {"alert_type": "unknown"})

        self.assertEqual(response.status_code, 400)


class FakeEsClient:
    """Stand-in datastore client whose ``update_by_query`` returns scripted responses.

    Mirrors the real behaviour being guarded against: Elasticsearch/OpenSearch's
    ``_update_by_query`` returns HTTP 200 with ``failures``/``version_conflicts``
    embedded in the body rather than raising, so the fake must do the same for
    the regression tests below to be meaningful.

    ``responses`` may be a single dict (returned on every call -- a conflict
    that never clears) or a list of dicts consumed one per call, with the last
    entry repeated once exhausted (so a test can model "the conflict clears on
    the Nth attempt").
    """

    def __init__(self, responses):
        self._responses = (
            list(responses) if isinstance(responses, list) else [responses]
        )
        self.calls = []

    def update_by_query(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


def _no_retry_delay(test_case):
    """Patch out the retry backoff sleep so conflict-retry tests run instantly."""
    patcher = patch.object(views.time, "sleep")
    test_case.addCleanup(patcher.stop)
    patcher.start()


class AlertHandleUpdateFailureTests(TestCase):
    """Regression tests for silently-dropped alert handle/clear updates, and for
    the retry-based hardening that replaces "detect and report" with "resolve the
    common case automatically."

    Before the first fix, ``handle_alerts``/``clear_all_data`` reported success
    as soon as Elasticsearch/OpenSearch returned HTTP 200 from
    ``update_by_query``, without checking whether any documents actually failed
    to update. A version conflict (e.g. two operators or browser tabs acting on
    overlapping alerts) left the alert's ``handled`` field unchanged while the
    UI reported success, so the alert reappeared on the next refresh despite the
    operator having "handled" it.

    The mutation is idempotent (selected by ``event.uuid``, not document
    ``_version``; the script always sets the same target field values
    regardless of who "wins" a race), so a version conflict is a timing
    artifact, not a real correctness problem -- the fundamental fix is to
    retry the identical request automatically rather than only report the
    conflict to the operator. Only a conflict that persists across every
    retry attempt (or a non-conflict failure, e.g. a script error) should
    surface as an error.
    """

    def setUp(self):
        self.factory = RequestFactory()
        _no_retry_delay(self)

    def post_json(self, view, payload):
        request = self.factory.post(
            "/alerts/test/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return view(request)

    def test_handle_alerts_transparently_retries_a_conflict_that_clears(self):
        """A conflict that resolves within the retry budget must not error."""
        fake_es = FakeEsClient(
            [
                {"updated": 0, "version_conflicts": 2, "failures": []},
                {"updated": 0, "version_conflicts": 1, "failures": []},
                {"updated": 2, "version_conflicts": 0, "failures": []},
            ]
        )
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(
                views.handle_alerts,
                {"handle_type": "dismissed", "uuids": ["alert-1", "alert-2"]},
            )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content.decode())
        self.assertEqual(body["message"], "2 alerts dismissed")
        # It took three attempts to clear -- confirm it actually retried
        # instead of getting lucky on the first call.
        self.assertEqual(len(fake_es.calls), 3)

    def test_handle_alerts_surfaces_a_conflict_that_never_clears_as_an_error(self):
        """A conflict that persists across every retry must still error out."""
        fake_es = FakeEsClient({"updated": 1, "version_conflicts": 2, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(
                views.handle_alerts,
                {"handle_type": "dismissed", "uuids": ["alert-1", "alert-2"]},
            )

        self.assertEqual(response.status_code, 502)
        body = json.loads(response.content.decode())
        self.assertIn("version conflict", body["error"])
        # It must have exhausted the full retry budget before giving up.
        self.assertEqual(len(fake_es.calls), views.ALERT_UPDATE_MAX_ATTEMPTS)

    def test_handle_alerts_does_not_retry_non_conflict_failures(self):
        """A script/mapping failure is not a timing artifact; retrying the
        identical request cannot fix it, so it must fail fast instead of
        burning the retry budget."""
        fake_es = FakeEsClient(
            {
                "updated": 0,
                "version_conflicts": 0,
                "failures": [
                    {"id": "alert-1", "cause": {"reason": "simulated script error"}}
                ],
            }
        )
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(
                views.handle_alerts,
                {"handle_type": "flagged", "uuids": ["alert-1"]},
            )

        self.assertEqual(response.status_code, 502)
        body = json.loads(response.content.decode())
        self.assertIn("simulated script error", body["error"])
        # Fails fast on the first attempt -- no point retrying a non-conflict.
        self.assertEqual(len(fake_es.calls), 1)

    def test_handle_alerts_reports_success_when_update_by_query_is_clean(self):
        fake_es = FakeEsClient({"updated": 2, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(
                views.handle_alerts,
                {"handle_type": "dismissed", "uuids": ["alert-1", "alert-2"]},
            )

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content.decode())
        self.assertEqual(body["message"], "2 alerts dismissed")
        self.assertEqual(len(fake_es.calls), 1)

    def test_handle_alerts_uses_conflicts_proceed_so_one_conflict_cannot_abort_the_batch(
        self,
    ):
        """``conflicts="proceed"`` must be requested so a single conflicting
        document cannot silently abort updates to the rest of the batch
        (the default ``"abort"`` would stop processing further hits)."""
        fake_es = FakeEsClient({"updated": 2, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            self.post_json(
                views.handle_alerts,
                {"handle_type": "dismissed", "uuids": ["alert-1", "alert-2"]},
            )

        self.assertEqual(fake_es.calls[0]["conflicts"], "proceed")

    def test_clear_all_data_transparently_retries_a_conflict_that_clears(self):
        fake_es = FakeEsClient(
            [
                {"updated": 0, "version_conflicts": 1, "failures": []},
                {"updated": 5, "version_conflicts": 0, "failures": []},
            ]
        )
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(views.clear_all_data, {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(fake_es.calls), 2)

    def test_clear_all_data_surfaces_a_conflict_that_never_clears_as_an_error(self):
        fake_es = FakeEsClient({"updated": 5, "version_conflicts": 1, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(views.clear_all_data, {})

        self.assertEqual(response.status_code, 502)
        body = json.loads(response.content.decode())
        self.assertIn("version conflict", body["error"])
        self.assertEqual(len(fake_es.calls), views.ALERT_UPDATE_MAX_ATTEMPTS)

    def test_clear_all_data_reports_success_when_update_by_query_is_clean(self):
        fake_es = FakeEsClient({"updated": 5, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(views.clear_all_data, {})

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content.decode())
        self.assertEqual(body["message"], "All alerts dismissed")

    def test_clear_all_data_uses_conflicts_proceed(self):
        fake_es = FakeEsClient({"updated": 5, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            self.post_json(views.clear_all_data, {})

        self.assertEqual(fake_es.calls[0]["conflicts"], "proceed")

    def test_dismissed_marks_selected_alerts_handled(self):
        """Dismissing selected alerts must hide them (handled=True) and record why."""
        fake_es = FakeEsClient({"updated": 2, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            self.post_json(
                views.handle_alerts,
                {"handle_type": "dismissed", "uuids": ["alert-1", "alert-2"]},
            )

        params = fake_es.calls[0]["body"]["script"]["params"]
        self.assertIs(params["status"], True)
        self.assertEqual(params["reason"], "dismissed")
        # Only the selected alerts are targeted -- never a match-all.
        self.assertEqual(
            fake_es.calls[0]["body"]["query"],
            {"terms": {"event.uuid.keyword": ["alert-1", "alert-2"]}},
        )

    def test_flagged_keeps_selected_alerts_active(self):
        """Flagging must NOT hide the alert: handled stays False."""
        fake_es = FakeEsClient({"updated": 1, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            response = self.post_json(
                views.handle_alerts,
                {"handle_type": "flagged", "uuids": ["alert-1"]},
            )

        params = fake_es.calls[0]["body"]["script"]["params"]
        self.assertIs(params["status"], False)
        self.assertEqual(params["reason"], "flagged")
        self.assertEqual(
            json.loads(response.content.decode())["message"], "1 alert flagged"
        )

    def test_legacy_false_positive_handle_type_is_rejected(self):
        """The old ``falsePositive`` type was replaced by ``dismissed``; a stale
        cached page posting it must fail loudly, not silently mis-record."""
        response = self.post_json(
            views.handle_alerts,
            {"handle_type": "falsePositive", "uuids": ["alert-1"]},
        )

        self.assertEqual(response.status_code, 400)

    def test_dismiss_all_targets_every_active_alert_not_a_selection(self):
        fake_es = FakeEsClient({"updated": 5, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            self.post_json(views.clear_all_data, {})

        self.assertEqual(
            fake_es.calls[0]["body"]["query"], {"term": {"handled": False}}
        )

    def test_every_dismiss_path_records_the_same_reason(self):
        """Dismiss Selected, Dismiss All and Dismiss All <section> must all store
        handled=True and acknowledge.reason='dismissed' with a timestamp, so
        'dismissed' reliably finds every dismissed alert."""
        fake_es = FakeEsClient({"updated": 2, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            self.post_json(
                views.handle_alerts,
                {"handle_type": "dismissed", "uuids": ["alert-1"]},
            )
            self.post_json(views.clear_all_data, {})
            self.post_json(views.clear_all_data, {"alert_type": "scpi_range"})
            self.post_json(views.clear_all_data, {"alert_type": "device"})

        self.assertEqual(len(fake_es.calls), 4)
        for call in fake_es.calls:
            script = call["body"]["script"]
            self.assertIs(script["params"]["status"], True)
            self.assertEqual(script["params"]["reason"], "dismissed")
            self.assertTrue(script["params"]["timestamp"])
            self.assertIn("acknowledge.reason = params.reason", script["source"])
            self.assertIn("acknowledge.timestamp = params.timestamp", script["source"])

    def test_dismiss_section_message_names_the_section(self):
        fake_es = FakeEsClient({"updated": 3, "version_conflicts": 0, "failures": []})
        with patch.object(views, "_get_database_client", return_value=fake_es):
            scpi = self.post_json(views.clear_all_data, {"alert_type": "scpi_range"})
            sysmon = self.post_json(views.clear_all_data, {"alert_type": "device"})

        self.assertEqual(
            json.loads(scpi.content.decode())["message"], "All SCPI alerts dismissed"
        )
        self.assertEqual(
            json.loads(sysmon.content.decode())["message"],
            "All Sysmon alerts dismissed",
        )


class HeavyUseAlertHandlingDurabilityTests(TestCase):
    """Simulate sustained/heavy operator use of handle/clear to check durability.

    Repeatedly handles alerts across many simulated requests, injecting
    occasional version conflicts (as concurrent operators/tabs racing the same
    alert would cause) to confirm that:

    1. a conflict that clears within the retry budget is resolved
       transparently -- the operator never sees an error for the common,
       expected-to-resolve-itself race, and
    2. a conflict that persists across every retry attempt (a genuinely rare
       condition) is still reported rather than silently dropped, and
    3. handling one request's retries/failure does not corrupt or block later
       requests.
    """

    def setUp(self):
        self.factory = RequestFactory()
        _no_retry_delay(self)

    def post_json(self, view, payload):
        request = self.factory.post(
            "/alerts/test/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return view(request)

    def test_long_running_handle_loop_resolves_transient_conflicts_automatically(
        self,
    ):
        resolved_count = 0
        persistent_error_count = 0

        for i in range(200):
            # Every 7th simulated request hits a transient conflict (another
            # operator/tab racing the same alert) that clears on retry.
            # Every 11th hits a conflict that never clears (a genuinely
            # pathological case worth surfacing).
            is_transient_conflict = i % 7 == 0
            is_persistent_conflict = i % 11 == 0

            if is_persistent_conflict:
                fake_es = FakeEsClient(
                    {"updated": 0, "version_conflicts": 1, "failures": []}
                )
            elif is_transient_conflict:
                fake_es = FakeEsClient(
                    [
                        {"updated": 0, "version_conflicts": 1, "failures": []},
                        {"updated": 1, "version_conflicts": 0, "failures": []},
                    ]
                )
            else:
                fake_es = FakeEsClient(
                    {"updated": 1, "version_conflicts": 0, "failures": []}
                )

            with patch.object(views, "_get_database_client", return_value=fake_es):
                response = self.post_json(
                    views.handle_alerts,
                    {"handle_type": "dismissed", "uuids": [f"alert-{i}"]},
                )

            if is_persistent_conflict:
                self.assertEqual(response.status_code, 502)
                persistent_error_count += 1
            else:
                # Both the clean case and the transiently-conflicted-then-
                # resolved case must succeed from the operator's perspective.
                self.assertEqual(response.status_code, 200)
                resolved_count += 1

        expected_persistent = len([i for i in range(200) if i % 11 == 0])
        self.assertEqual(persistent_error_count, expected_persistent)
        self.assertEqual(resolved_count, 200 - expected_persistent)
        # The vast majority of simulated requests resolved without the
        # operator ever seeing an error, despite frequent injected conflicts.
        self.assertGreater(resolved_count, persistent_error_count)


class FakeSearchTopEsClient:
    """Datastore test double for the bounded alert query path (``search_top``)."""

    def __init__(self, documents, total):
        self._documents = documents
        self._total = total
        self.calls = []

    def search_top(self, index, query=None, sort=None, size=10000, return_fields=None):
        self.calls.append(
            {"index": index, "query": query, "sort": sort, "size": size}
        )
        # Honour the cap the view requests, as a real bounded search would.
        return self._documents[:size], self._total


class AlertQueryBuildingTests(TestCase):
    """Tests for how the alerts view queries the datastore.

    These pin the correctness/robustness properties that are invisible to a
    single-index happy-path fixture but matter across many daily ``alerts-*``
    indices under long-term use:
      - exact-keyword matching on ``agent.type`` (not analyzed ``match``);
      - a bounded fetch with an honest total (no unbounded materialisation);
      - a sort hardened against unmapped fields on fresh daily indices.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def post_json(self, view, payload):
        request = self.factory.post(
            "/alerts/test/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return view(request)

    def test_build_alert_filter_uses_exact_keyword_term_on_agent_type(self):
        filters = views._build_alert_filter("scpi_range")
        # handled must be an exact boolean term.
        assert {"term": {"handled": False}} in filters
        # agent.type must be matched as an exact term on the .keyword subfield,
        # never an analyzed match (which depends on analyzer behaviour and can
        # drift across indices).
        should = filters[1]["bool"]["should"]
        assert should == [
            {"term": {"agent.type.keyword": "ScpiValueRangesAnalytic"}},
            {"term": {"agent.type.keyword": "ScpiCompareAnalytic"}},
        ]
        for clause in should:
            assert "match" not in clause

    def test_alert_sort_is_hardened_against_unmapped_fields(self):
        sort = views._alert_sort()
        # The @timestamp sort must declare unmapped_type so a brand-new daily
        # index without that mapping cannot fail a shard.
        ts_sort = next(s for s in sort if "@timestamp" in s)
        assert ts_sort["@timestamp"]["unmapped_type"] == "date"
        # The script sort must guard the field existence (containsKey).
        script_sort = next(s for s in sort if "_script" in s)
        assert "containsKey" in script_sort["_script"]["script"]["source"]

    def test_alert_query_returns_bounded_results_with_total(self):
        docs = [{"event": {"uuid": f"u{i}"}} for i in range(5)]
        fake_es = FakeSearchTopEsClient(documents=docs, total=4718)
        with patch.object(views, "_get_database_client", return_value=fake_es), patch.object(
            views, "ALERT_QUERY_MAX_RESULTS", 3
        ):
            response = self.post_json(views.alert_query, {"alert_type": "scpi_range"})

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content.decode())
        # Bounded to the cap...
        self.assertEqual(len(body["alerts"]), 3)
        # ...but the true total is reported so the UI never lies about volume.
        self.assertEqual(body["total"], 4718)
        # The view must have asked the datastore for a bounded search with the
        # cap as the size, not an unbounded scroll.
        self.assertEqual(fake_es.calls[0]["size"], 3)
        self.assertEqual(fake_es.calls[0]["index"], views.ALERT_INDEX_PATTERN)

    def test_alert_snapshot_includes_totals_per_column(self):
        docs = [{"event": {"uuid": "u1"}}]
        fake_es = FakeSearchTopEsClient(documents=docs, total=42)
        snapshot = views._get_alert_snapshot(fake_es)

        self.assertIn("totals", snapshot)
        self.assertEqual(set(snapshot["totals"].keys()), set(views.ALERT_TYPE_ANALYTICS))
        for alert_type in views.ALERT_TYPE_ANALYTICS:
            self.assertEqual(snapshot["totals"][alert_type], 42)
            self.assertEqual(len(snapshot["alerts"][alert_type]), 1)


class LifecycleFakeClient(FakeSearchTopEsClient):
    """Bounded-query fake that also records ``close()`` and can be told to fail."""

    def __init__(self, documents=None, total=0, fail_search=False, fail_close=False):
        super().__init__(documents if documents is not None else [], total)
        self.fail_search = fail_search
        self.fail_close = fail_close
        self.close_calls = 0

    def search_top(self, *args, **kwargs):
        if self.fail_search:
            raise ConnectionError("datastore unreachable")
        return super().search_top(*args, **kwargs)

    def close(self):
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("close blew up")


class LifecycleUpdateClient(FakeEsClient):
    """``update_by_query`` fake that also records ``close()``."""

    def __init__(self):
        super().__init__({"updated": 1, "version_conflicts": 0, "failures": []})
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class ClientFactory:
    """Stand-in for ``_get_database_client`` that records every client it builds."""

    def __init__(self, *clients):
        self._queue = list(clients)
        self.built = []

    def __call__(self, request):
        client = self._queue.pop(0) if self._queue else LifecycleFakeClient()
        self.built.append(client)
        return client


def _fast_stream(test_case, *, heartbeat_seconds=None):
    """Remove real waiting from stream tests; optionally shrink the heartbeat.

    With the default (30s) heartbeat an unchanged poll yields nothing, so a test
    that pulls frames one at a time must pass ``heartbeat_seconds=0`` to make
    every poll yield, or it would spin forever waiting for a frame.
    """
    patchers = [
        patch.object(views, "ALERT_STREAM_POLL_SECONDS", 0),
        patch.object(views.time, "sleep"),
    ]
    if heartbeat_seconds is not None:
        patchers.append(
            patch.object(views, "ALERT_STREAM_HEARTBEAT_SECONDS", heartbeat_seconds)
        )
    for patcher in patchers:
        test_case.addCleanup(patcher.stop)
        patcher.start()


def _event_names(frames):
    """Return the SSE event name of each frame (``None`` for comment frames)."""
    names = []
    for frame in frames:
        if frame.startswith(":"):
            names.append(None)
        else:
            names.append(frame.split("\n", 1)[0].removeprefix("event: "))
    return names


class AlertStreamClientLifecycleTests(TestCase):
    """The stream must hold ONE datastore client for its whole life and release it.

    Before this, every poll built a new client (new connection pool, new
    TCP/TLS handshake) for each of the two columns, none of them ever closed --
    roughly 24 abandoned clients a minute per open tab, for weeks.
    """

    POLLS = 10

    def setUp(self):
        self.request = RequestFactory().get("/alerts/alert-stream/")

    def test_one_client_is_reused_across_many_polls(self):
        _fast_stream(self, heartbeat_seconds=0)
        client = LifecycleFakeClient(documents=[{"event": {"uuid": "u1"}}], total=1)
        build = ClientFactory(client)
        stream = views._sync_alert_event_stream(self.request)

        with patch.object(views, "_get_database_client", build):
            frames = [next(stream) for _ in range(1 + self.POLLS)]
            stream.close()

        # ": connected", one snapshot, then a heartbeat per unchanged poll.
        self.assertEqual(
            _event_names(frames),
            [None, "alert_snapshot"] + ["heartbeat"] * (self.POLLS - 1),
        )
        self.assertEqual(len(build.built), 1)
        # Two columns per poll, every one of them on the same client.
        self.assertEqual(len(client.calls), 2 * self.POLLS)

    def test_client_is_closed_when_the_consumer_disconnects(self):
        _fast_stream(self)
        client = LifecycleFakeClient()
        build = ClientFactory(client)
        stream = views._sync_alert_event_stream(self.request)

        with patch.object(views, "_get_database_client", build):
            next(stream)
            next(stream)
            self.assertEqual(client.close_calls, 0)
            stream.close()  # what the WSGI server does on client disconnect

        self.assertEqual(client.close_calls, 1)

    def test_no_client_is_built_if_the_stream_is_abandoned_before_first_poll(self):
        _fast_stream(self)
        build = ClientFactory()
        stream = views._sync_alert_event_stream(self.request)

        with patch.object(views, "_get_database_client", build):
            next(stream)  # only ": connected"
            stream.close()

        self.assertEqual(build.built, [])

    def test_failed_client_is_discarded_and_rebuilt_on_the_next_poll(self):
        """A client that raised may hold dead pooled connections (datastore
        restart, network fault); it must be closed and replaced, not reused."""
        _fast_stream(self)
        broken = LifecycleFakeClient(fail_search=True)
        healthy = LifecycleFakeClient(documents=[{"event": {"uuid": "u1"}}], total=1)
        build = ClientFactory(broken, healthy)
        stream = views._sync_alert_event_stream(self.request)

        with patch.object(views, "_get_database_client", build):
            frames = [next(stream) for _ in range(3)]
            stream.close()

        self.assertEqual(_event_names(frames), [None, "alert_error", "alert_snapshot"])
        self.assertEqual(build.built, [broken, healthy])
        self.assertEqual(broken.close_calls, 1)
        self.assertEqual(healthy.close_calls, 1)

    def test_error_frame_survives_a_client_that_cannot_be_closed(self):
        _fast_stream(self)
        broken = LifecycleFakeClient(fail_search=True, fail_close=True)
        build = ClientFactory(broken)
        stream = views._sync_alert_event_stream(self.request)

        with patch.object(views, "_get_database_client", build):
            next(stream)
            error_frame = next(stream)
            stream.close()

        self.assertEqual(_event_names([error_frame]), ["alert_error"])
        self.assertIn("datastore unreachable", error_frame)

    def test_unchanged_data_sends_a_named_heartbeat_event(self):
        """Heartbeats must be real events: SSE comments are invisible to the
        browser, so a silently dead connection could not be told from 'no change'."""
        _fast_stream(self, heartbeat_seconds=0)
        client = LifecycleFakeClient(documents=[{"event": {"uuid": "u1"}}], total=1)
        build = ClientFactory(client)
        stream = views._sync_alert_event_stream(self.request)

        with patch.object(views, "_get_database_client", build):
            frames = [next(stream) for _ in range(3)]
            stream.close()

        self.assertEqual(_event_names(frames), [None, "alert_snapshot", "heartbeat"])
        payload = json.loads(frames[2].split("data: ", 1)[1])
        self.assertIn("checked_at", payload)
        self.assertEqual(payload["interval_seconds"], 0)
        # No legacy comment-style heartbeat (a bare ": heartbeat" line).
        lines = "".join(frames).splitlines()
        self.assertNotIn(": heartbeat", lines)

    def test_closed_source_refuses_to_build_a_new_client(self):
        """A fetch racing a disconnect must not leak a fresh connection pool."""
        build = ClientFactory()
        source = views._AlertSnapshotSource(self.request)
        source.close()

        with patch.object(views, "_get_database_client", build):
            with self.assertRaises(RuntimeError):
                source.fetch()

        self.assertEqual(build.built, [])

    def test_source_close_is_idempotent(self):
        client = LifecycleFakeClient()
        build = ClientFactory(client)
        source = views._AlertSnapshotSource(self.request)

        with patch.object(views, "_get_database_client", build):
            source.fetch()
            source.close()
            source.close()

        self.assertEqual(client.close_calls, 1)

    def test_closing_during_an_in_flight_fetch_waits_for_it_to_finish(self):
        """A browser disconnect cancels the stream while a worker thread is
        still mid-query. Closing the client at that moment makes the rest of the
        query fail with "Pool is closed" (the datastore transport then retries it
        and logs a traceback each time). The client must be released only once
        the in-flight fetch has finished, and then exactly once."""
        entered = threading.Event()
        release = threading.Event()

        class BlockingClient(LifecycleFakeClient):
            def __init__(self):
                super().__init__(documents=[], total=0)
                self.closed_when_queried = []

            def search_top(self, *args, **kwargs):
                self.closed_when_queried.append(self.close_calls)
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("test never released the blocked query")
                return super().search_top(*args, **kwargs)

        client = BlockingClient()
        build = ClientFactory(client)
        source = views._AlertSnapshotSource(self.request)
        results = []

        with patch.object(views, "_get_database_client", build):
            worker = threading.Thread(target=lambda: results.append(source.fetch()))
            worker.start()
            self.assertTrue(entered.wait(timeout=5))

            source.close()  # the disconnect arrives mid-query
            self.assertEqual(client.close_calls, 0, "closed under a running query")

            release.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1, "the in-flight fetch must still complete")
        # Every column's query ran against a client that was still open.
        self.assertEqual(client.closed_when_queried, [0] * len(views.ALERT_TYPE_ANALYTICS))
        self.assertEqual(client.close_calls, 1)

    def test_a_fetch_that_fails_after_close_still_releases_the_client_once(self):
        entered = threading.Event()
        release = threading.Event()

        class FailingBlockingClient(LifecycleFakeClient):
            def search_top(self, *args, **kwargs):
                entered.set()
                release.wait(timeout=5)
                raise ConnectionError("datastore went away")

        client = FailingBlockingClient()
        build = ClientFactory(client)
        source = views._AlertSnapshotSource(self.request)
        errors = []

        def run():
            try:
                source.fetch()
            except ConnectionError as exc:
                errors.append(exc)

        with patch.object(views, "_get_database_client", build):
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(entered.wait(timeout=5))
            source.close()
            release.set()
            worker.join(timeout=5)

        self.assertEqual(len(errors), 1)
        self.assertEqual(client.close_calls, 1)


class AsyncAlertStreamLifecycleTests(TestCase):
    """ASGI path: cancellation must propagate and the client must still be released."""

    def setUp(self):
        self.request = RequestFactory().get("/alerts/alert-stream/")
        _fast_stream(self)

    def test_client_is_closed_when_the_stream_is_closed(self):
        client = LifecycleFakeClient(documents=[{"event": {"uuid": "u1"}}], total=1)
        build = ClientFactory(client)

        async def drive():
            stream = views._async_alert_event_stream(self.request)
            frames = [await stream.__anext__(), await stream.__anext__()]
            await stream.aclose()
            return frames

        with patch.object(views, "_get_database_client", build):
            frames = asyncio.run(drive())

        self.assertEqual(_event_names(frames), [None, "alert_snapshot"])
        self.assertEqual(len(build.built), 1)
        self.assertEqual(client.close_calls, 1)

    def test_cancellation_is_not_swallowed_and_still_releases_the_client(self):
        """Catching CancelledError and breaking hides cancellation from asyncio;
        it must propagate while the finally block releases the client."""
        client = LifecycleFakeClient()
        build = ClientFactory(client)

        async def drive():
            stream = views._async_alert_event_stream(self.request)

            async def consume():
                async for _ in stream:
                    pass

            task = asyncio.ensure_future(consume())
            for _ in range(500):  # up to ~5s for the worker thread's first fetch
                await asyncio.sleep(0.01)
                if client.calls:
                    break
            self.assertTrue(client.calls, "stream never queried the datastore")
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with patch.object(views, "_get_database_client", build):
            asyncio.run(drive())

        self.assertEqual(client.close_calls, 1)


class RequestScopedClientTests(TestCase):
    """Non-streaming endpoints must close the client they open."""

    def setUp(self):
        self.factory = RequestFactory()
        _no_retry_delay(self)

    def post_json(self, view, payload):
        request = self.factory.post(
            "/alerts/test/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        return view(request)

    def test_alert_query_closes_its_client(self):
        client = LifecycleFakeClient(documents=[], total=0)
        with patch.object(views, "_get_database_client", return_value=client):
            response = self.post_json(views.alert_query, {"alert_type": "device"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.close_calls, 1)

    def test_alert_query_closes_its_client_when_the_search_fails(self):
        client = LifecycleFakeClient(fail_search=True)
        with patch.object(views, "_get_database_client", return_value=client):
            response = self.post_json(views.alert_query, {"alert_type": "device"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(client.close_calls, 1)

    def test_a_close_failure_does_not_change_the_response(self):
        client = LifecycleFakeClient(documents=[], total=0, fail_close=True)
        with patch.object(views, "_get_database_client", return_value=client):
            response = self.post_json(views.alert_query, {"alert_type": "device"})

        self.assertEqual(response.status_code, 200)

    def test_handle_and_clear_close_their_client(self):
        for view, payload in (
            (views.handle_alerts, {"handle_type": "dismissed", "uuids": ["a"]}),
            (views.clear_all_data, {}),
        ):
            client = LifecycleUpdateClient()
            with patch.object(views, "_get_database_client", return_value=client):
                response = self.post_json(view, payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.close_calls, 1)

