"""Render tests for client-side UTC-to-local timestamp hydration.

Each timestamp is emitted as an ISO-8601 string inside a ``data-timestamp``
attribute on a ``<time>`` element; ``parseusDatetime.hydrateTimestamps()``
(loaded globally from base.html) fills in the viewer-local display text at
runtime. These tests pin that the raw ISO-8601 value survives into
``data-timestamp`` unmolested, and that templates no longer interpolate the
server-rendered datetime text directly.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory


def _request_with_session():
    """Build a GET request carrying an empty session for context processors."""
    from importlib import import_module

    from django.conf import settings as dj_settings

    request = RequestFactory().get("/")
    engine = import_module(dj_settings.SESSION_ENGINE)
    request.session = engine.SessionStore()
    return request


CREATED_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
UPDATED_AT = datetime(2024, 1, 3, 4, 5, 6, tzinfo=timezone.utc)


def test_run_details_hydrates_created_timestamp():
    """run_details.html emits a hydration-ready <time> for object.created."""
    request = _request_with_session()
    html = render_to_string(
        "peat/run_details.html",
        {
            "object": SimpleNamespace(
                name="demo-pull",
                run_dir="demo-pull",
                status="done",
                created=CREATED_AT,
                config=None,
                get_method=lambda: "pull",
                pk=1,
            )
        },
        request=request,
    )

    assert 'data-timestamp="2024-01-02T03:04:05+00:00"' in html
    # The <time> element starts with the server-rendered fallback text (so
    # non-JS/pre-hydration viewers still see something meaningful) which
    # hydrateTimestamps() overwrites with the viewer-local rendering.
    assert '<time data-timestamp="2024-01-02T03:04:05+00:00">Jan. 2, 2024' in html


def test_peatconfig_detail_hydrates_created_and_updated_timestamps():
    """peatconfig_detail.html emits hydration-ready <time> elements for both fields."""
    request = _request_with_session()
    html = render_to_string(
        "peat/peatconfig_detail.html",
        {
            "object": SimpleNamespace(
                name="demo-config",
                description="",
                author="",
                debug=0,
                intensive_scan=False,
                assume_online=False,
                created=CREATED_AT,
                updated=UPDATED_AT,
                hosts=SimpleNamespace(count=lambda: 0),
                pulls=SimpleNamespace(count=lambda: 0),
                scans=SimpleNamespace(count=lambda: 0),
                filename=SimpleNamespace(url="/media/peat/demo.yaml"),
                pk=1,
            )
        },
        request=request,
    )

    assert 'data-timestamp="2024-01-02T03:04:05+00:00"' in html
    assert 'data-timestamp="2024-01-03T04:05:06+00:00"' in html


def test_peatconfig_list_hydrates_compact_timestamps():
    """peatconfig_list.html uses the compact style for its dense table rows."""
    request = _request_with_session()
    html = render_to_string(
        "peat/peatconfig_list.html",
        {
            "object_list": [
                SimpleNamespace(
                    id=1,
                    pk=1,
                    name="demo-config",
                    description="",
                    author="",
                    created=CREATED_AT,
                    updated=UPDATED_AT,
                )
            ],
            "page_obj": None,
            "is_paginated": False,
        },
        request=request,
    )

    assert 'data-timestamp="2024-01-02T03:04:05+00:00" data-timestamp-style="compact"' in html
    assert 'data-timestamp="2024-01-03T04:05:06+00:00" data-timestamp-style="compact"' in html


def test_modal_metadata_hydrates_created_at_without_hardcoded_utc_label():
    """modal_metadata.html drops the hardcoded "UTC" suffix now that the value is localized."""
    html = render_to_string(
        "analytics/modal_metadata.html",
        {
            "model": SimpleNamespace(
                pk=1,
                instance_name="demo-model",
                analytic=SimpleNamespace(model="DemoModel", name="DemoAnalytic"),
                drawing_data="",
                trainedmodelmetadata_set=SimpleNamespace(
                    all=lambda: [
                        SimpleNamespace(
                            created_at=CREATED_AT,
                            es_host="",
                            idx="",
                            query="",
                            aggs="",
                            comp_aggs="",
                            return_fields="",
                            ip_filter="",
                            start_date="",
                            end_date="",
                        )
                    ]
                ),
            )
        },
    )

    assert 'data-timestamp="2024-01-02T03:04:05+00:00"' in html
    assert "UTC</td>" not in html
