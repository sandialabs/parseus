"""Parser that lifts structured metadata out of analytic docstrings.

Historically every analytic carried a structured block in its class docstring
(``How:``, ``When:``, ``Usage:``, ``Mitre-Techniques:``, ``Purdue-Levels:``,
``Tags:``) that nothing ever parsed -- the whole docstring was shown verbatim.
This module turns those blocks into typed values so the descriptor can expose
them as first-class fields (summary, detection_logic, mitre_techniques, ...).

The docstrings are hand-written and inconsistent (blank blocks, ``Name:``
headers, ``level 1`` vs ``level-1``, technique IDs sometimes present), so the
parser is deliberately tolerant: unknown or empty blocks are ignored and missing
blocks simply yield empty values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Section headers we recognise, mapped to a normalised key. Matching is
# case-insensitive and tolerant of surrounding whitespace.
_SECTION_ALIASES = {
    "name": "name",
    "how": "how",
    "when": "when",
    "usage": "usage",
    "mitre-data-sources": "mitre_data_sources",
    "mitre-techniques": "mitre_techniques",
    "purdue-levels": "purdue_levels",
    "tags": "tags",
}

# A line that starts a section: "Mitre-Techniques:" alone, or "How: inline text"
# where any text after the colon becomes the section's first content line.
_HEADER_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _-]*?)\s*:\s*(.*)$")
# A bullet line like "+ level 1" or "  + Network Sniffing (T1040)".
_BULLET_RE = re.compile(r"^\s*[-+*]\s+(.*\S)\s*$")
# A trailing MITRE-style id in parentheses, e.g. "(T0841)" or "(TA0100)".
_TECHNIQUE_ID_RE = re.compile(r"\(?\b(T[A-Z]?\d{3,})\b\)?")
# A Purdue level expressed as "level 1", "level-2", "1", etc.
_PURDUE_LEVEL_RE = re.compile(r"level[\s_-]*([0-9]+)", re.IGNORECASE)


@dataclass
class DocstringMetadata:
    """Structured values extracted from an analytic docstring."""

    summary: str = ""
    detection_logic: str = ""
    usage: str = ""
    mitre_techniques: list[str] = field(default_factory=list)
    purdue_levels: list[int] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def _split_sections(docstring: str) -> dict[str, list[str]]:
    """Group the docstring's lines under their recognised section headers.

    Lines before the first recognised header are collected under an empty key so
    a leading free-text summary is still available.
    """
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for raw_line in docstring.splitlines():
        header_match = _HEADER_RE.match(raw_line)
        if header_match:
            candidate = header_match.group(1).strip().lower()
            if candidate in _SECTION_ALIASES:
                current = _SECTION_ALIASES[candidate]
                sections.setdefault(current, [])
                inline = header_match.group(2).strip()
                if inline:
                    sections[current].append(inline)
                continue
        sections.setdefault(current, []).append(raw_line)
    return sections


def _bullets(lines: list[str]) -> list[str]:
    """Return the ``+ value`` bullet items from a block, in order."""
    items: list[str] = []
    for line in lines:
        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            items.append(bullet_match.group(1).strip())
    return items


def _free_text(lines: list[str]) -> str:
    """Collapse a free-text block into a single normalised string."""
    return " ".join(part.strip() for part in lines if part.strip())


def _mitre_techniques(lines: list[str]) -> list[str]:
    """Extract MITRE technique/tactic IDs from a Mitre-Techniques block.

    Only well-formed IDs (``T####``/``TA####``) are kept; descriptive-only
    bullets without an ID are ignored so the field stays clean and linkable.
    """
    techniques: list[str] = []
    seen: set[str] = set()
    for item in _bullets(lines):
        for match in _TECHNIQUE_ID_RE.finditer(item):
            technique_id = match.group(1)
            if technique_id not in seen:
                seen.add(technique_id)
                techniques.append(technique_id)
    return techniques


def _purdue_levels(lines: list[str]) -> list[int]:
    """Extract integer Purdue levels from a Purdue-Levels block."""
    levels: list[int] = []
    seen: set[int] = set()
    for item in _bullets(lines):
        match = _PURDUE_LEVEL_RE.search(item)
        if not match:
            match = re.search(r"\b([0-9]+)\b", item)
        if match:
            level = int(match.group(1))
            if level not in seen:
                seen.add(level)
                levels.append(level)
    return levels


def _summary(sections: dict[str, list[str]]) -> str:
    """Pick a short human summary from the ``How:`` block or the lead text."""
    how_text = _free_text(sections.get("how", []))
    if how_text:
        return how_text
    lead = _free_text(
        [line for line in sections.get("", []) if not _HEADER_RE.match(line)]
    )
    return lead


def parse_docstring_metadata(docstring: str | None) -> DocstringMetadata:
    """Parse an analytic's class docstring into structured metadata.

    :param docstring: The analytic class ``__doc__`` (may be ``None``).
    :return: A :class:`DocstringMetadata`; empty when there is nothing to parse.
    """
    if not docstring:
        return DocstringMetadata()

    sections = _split_sections(docstring)
    return DocstringMetadata(
        summary=_summary(sections),
        detection_logic=_free_text(sections.get("how", [])),
        usage=_free_text(sections.get("usage", [])),
        mitre_techniques=_mitre_techniques(sections.get("mitre_techniques", [])),
        purdue_levels=_purdue_levels(sections.get("purdue_levels", [])),
        labels=_bullets(sections.get("tags", [])),
    )
