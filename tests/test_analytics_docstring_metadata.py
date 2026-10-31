"""Tests for lifting structured metadata out of analytic docstrings."""

from parseus.analytics.docstring_metadata import (
    DocstringMetadata,
    parse_docstring_metadata,
)


SAMPLE_DOCSTRING = """
    Name: OTFunctionCodeAnalytic

    How: Calculates OT function codes per source/dest ip based on their rate.
         If the rate increases an alert fires.

    When: Detect a device that might be compromised or enumerated.

    Usage: Not Listed

    Mitre-Data-Sources:
        + Network Traffic: Network Traffic Content

    Mitre-Techniques:
        + impair-process-control (TA0106)
        + Device Restart/Shutdown (T0816)
        + Command: Command Execution

    Purdue-Levels:
        + level 1
        + level-2

    Tags:
        + Change
        + scanning
"""


def test_parse_returns_empty_for_missing_docstring():
    assert parse_docstring_metadata(None) == DocstringMetadata()
    assert parse_docstring_metadata("") == DocstringMetadata()


def test_parse_summary_and_detection_logic_from_how_block():
    metadata = parse_docstring_metadata(SAMPLE_DOCSTRING)

    assert metadata.detection_logic.startswith("Calculates OT function codes")
    # How: also drives the short summary.
    assert metadata.summary == metadata.detection_logic


def test_parse_extracts_only_well_formed_mitre_ids():
    metadata = parse_docstring_metadata(SAMPLE_DOCSTRING)

    # IDs are kept in order; the descriptive-only "Command: Command Execution"
    # bullet (no ID) is dropped.
    assert metadata.mitre_techniques == ["TA0106", "T0816"]


def test_parse_extracts_integer_purdue_levels_from_mixed_formats():
    metadata = parse_docstring_metadata(SAMPLE_DOCSTRING)

    # Handles both "level 1" and "level-2".
    assert metadata.purdue_levels == [1, 2]


def test_parse_extracts_tag_labels():
    metadata = parse_docstring_metadata(SAMPLE_DOCSTRING)

    assert metadata.labels == ["Change", "scanning"]


def test_parse_uses_lead_text_when_no_how_block():
    docstring = """
    A short lead description of the analytic.

    Purdue-Levels:
        + level 3
    """

    metadata = parse_docstring_metadata(docstring)

    assert metadata.summary == "A short lead description of the analytic."
    assert metadata.detection_logic == ""
    assert metadata.purdue_levels == [3]


def test_parse_tolerates_empty_blocks():
    docstring = """
    Name: SysmonUnapprovedIpAnalytic

    How: Looks for IP references that are not in the whitelist.

    When:

    Mitre-Techniques:


    Purdue-Levels:
        + level 2
    """

    metadata = parse_docstring_metadata(docstring)

    assert metadata.detection_logic.startswith("Looks for IP references")
    assert metadata.mitre_techniques == []
    assert metadata.purdue_levels == [2]
    assert metadata.labels == []
