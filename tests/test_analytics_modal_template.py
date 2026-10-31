"""Render tests for the analytic description modal after metadata refactor.

The modal is a self-contained fragment (no ``{% extends %}``), so it renders
without a request/context processors. These guard that the modal shows the typed
metadata fields and no longer depends on the removed ``class_desc``.
"""

from types import SimpleNamespace

from django.template.loader import render_to_string


def _analytic(**overrides):
    base = {
        "name": "SysmonUnapprovedIpAnalytic",
        "model": "SysmonUnapprovedIpAnalytic",
        "summary": "Detects unwhitelisted IP references.",
        "detection_logic": "Compares observed IPs against an allow list.",
        "mitre_techniques": ["T1040", "TA0100"],
        "purdue_levels": [2, 3],
        "labels": ["scanning", "windows"],
        "train_desc": "",
        "predict_desc": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_modal_renders_typed_metadata_fields():
    html = render_to_string(
        "analytics/modal_analytic_desc.html", {"analytic": _analytic()}
    )

    assert "Detects unwhitelisted IP references." in html
    assert "Compares observed IPs against an allow list." in html
    assert "T1040" in html
    assert "TA0100" in html
    assert "Level 2" in html
    assert "scanning" in html
    assert "windows" in html
    # The raw class-description block is gone.
    assert "Class Description" not in html


def test_modal_omits_empty_metadata_sections():
    html = render_to_string(
        "analytics/modal_analytic_desc.html",
        {
            "analytic": _analytic(
                summary="",
                detection_logic="",
                mitre_techniques=[],
                purdue_levels=[],
                labels=[],
            )
        },
    )

    assert "Summary" not in html
    assert "Detection Logic" not in html
    assert "MITRE Techniques" not in html
    assert "Purdue Levels" not in html
    assert "Labels" not in html
    # The model heading is always shown.
    assert "Model" in html


# --- trained-model metadata modal: empty "Drawing data" state -----------------

import pandas as pd  # noqa: E402  (grouped with the tests that use it)

NO_DATA_MESSAGE = "No training data"


def _render_metadata_modal(drawing_data):
    from datetime import datetime, timezone

    meta = SimpleNamespace(
        created_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
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
    model = SimpleNamespace(
        pk=1,
        instance_name="demo-model",
        analytic=SimpleNamespace(model="DemoModel", name="DemoAnalytic"),
        drawing_data=drawing_data,
        trainedmodelmetadata_set=SimpleNamespace(all=lambda: [meta]),
    )
    return render_to_string("analytics/modal_metadata.html", {"model": model})


def _as_stored(df):
    """Mirror how utility_analytics.train stores fit results."""
    return df.to_html(classes="table table-striped table-bordered")


def test_modal_says_so_when_training_data_is_an_empty_table():
    # What a model trained on no data actually has stored: a header-only <table>.
    html = _render_metadata_modal(_as_stored(pd.DataFrame()))

    assert NO_DATA_MESSAGE in html
    assert "dataframe" not in html  # the empty table is not rendered


def test_modal_says_so_when_training_data_has_columns_but_no_rows():
    html = _render_metadata_modal(_as_stored(pd.DataFrame(columns=["a", "b"])))

    assert NO_DATA_MESSAGE in html
    assert "dataframe" not in html


def test_modal_says_so_when_training_data_is_blank_or_null():
    for blank in ("", None):
        html = _render_metadata_modal(blank)

        assert NO_DATA_MESSAGE in html
        assert "<code>" not in html


def test_modal_still_renders_a_populated_training_table():
    html = _render_metadata_modal(_as_stored(pd.DataFrame({"a": [1, 2]})))

    assert "dataframe" in html
    assert "<td>1</td>" in html
    assert NO_DATA_MESSAGE not in html


def test_modal_still_renders_non_table_training_output_as_code():
    html = _render_metadata_modal("some plain fit summary")

    assert "<code>some plain fit summary</code>" in html
    assert NO_DATA_MESSAGE not in html
