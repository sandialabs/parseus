"""Page ``<title>`` tests for the shared ``base.html`` title block.

``base.html`` defines ``{% block title %}Parseus{% endblock %}`` and every page
template overrides it as ``<Page> | {{ block.super }}`` so the site name lives in
exactly one place and the distinguishing part comes first (it stays visible in
narrow browser tabs / history lists).

The real ``base.html`` cannot be rendered in a unit test: its ``{% compress %}``
tag needs the offline compression manifest. So these tests swap in a stub base
that only contains the title and body blocks, and render each *real* page
template through a tiny grandchild that blanks the heavy body blocks. The title
inheritance chain (page -> base) is the real code under test; the page bodies
(URL reversing, ORM objects, ...) are deliberately not exercised.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from django.template import Context, Engine
from django.template.backends.django import get_installed_libraries

WEBAPP = Path(__file__).resolve().parents[1] / "src" / "parseus" / "webapp"
TEMPLATE_DIRS = [str(p) for p in sorted(WEBAPP.glob("*/templates"))]

STUB_BASE = (
    "<title>{% block title %}Parseus{% endblock %}</title>"
    "{% block custom_styles %}{% endblock %}"
    "{% block content %}{% endblock %}"
    "{% block custom_scripts %}{% endblock %}"
)


def _grandchild(page: str) -> str:
    return (
        f'{{% extends "{page}" %}}'
        "{% block custom_styles %}{% endblock %}"
        "{% block content %}{% endblock %}"
        "{% block custom_scripts %}{% endblock %}"
    )


def _render_title(page: str, **context) -> str:
    engine = Engine(
        dirs=TEMPLATE_DIRS,
        # Same tag libraries the real DjangoTemplates backend registers, so the
        # pages' ``{% load static %}`` etc. compile exactly as in production.
        libraries=get_installed_libraries(),
        loaders=[
            (
                "django.template.loaders.locmem.Loader",
                {"base.html": STUB_BASE, "__page__.html": _grandchild(page)},
            ),
            "django.template.loaders.filesystem.Loader",
        ],
    )
    html = engine.get_template("__page__.html").render(Context(context))
    start = html.index("<title>") + len("<title>")
    return html[start : html.index("</title>")]


def _obj(**kw):
    return SimpleNamespace(**kw)


# (template, context, expected full <title>)
STATIC_PAGES = [
    ("registration/login.html", {}, "Sign in | Parseus"),
    ("analytics/analytic_base.html", {}, "Analytics | Parseus"),
    ("analytics/supervised_analytics.html", {}, "Supervised Analytics | Parseus"),
    ("analytics/unsupervised_analytics.html", {}, "Unsupervised Analytics | Parseus"),
    ("registers/register_base.html", {}, "OT Registers | Parseus"),
    ("registers/register_analysis.html", {}, "Register Analysis | Parseus"),
    ("alerts/index.html", {}, "Alert Operations | Parseus"),
    ("alerts/sysmon_rules.html", {}, "Sysmon Rule Deck | Parseus"),
    ("peat/home.html", {}, "PEAT | Parseus"),
    ("peat/peat_scan.html", {}, "Default PEAT Runs | Parseus"),
    ("peat/peatconfig_build.html", {}, "Create PEAT Configuration | Parseus"),
    ("peat/peatconfig_list.html", {}, "PEAT Configurations | Parseus"),
]


@pytest.mark.parametrize("page,context,expected", STATIC_PAGES)
def test_static_page_titles(page, context, expected):
    assert _render_title(page, **context) == expected


def test_home_keeps_plain_site_name():
    """``home.html`` intentionally does not override the title block."""
    assert _render_title("home.html") == "Parseus"


def test_sysmon_rule_form_title_comes_from_view_context():
    assert (
        _render_title("alerts/sysmon_rule_form.html", title="Create Sysmon Rule")
        == "Create Sysmon Rule | Parseus"
    )
    assert (
        _render_title("alerts/sysmon_rule_form.html", title="Edit Sysmon Rule")
        == "Edit Sysmon Rule | Parseus"
    )


def test_peat_config_detail_title_includes_config_name():
    assert (
        _render_title("peat/peatconfig_detail.html", object=_obj(name="plant-a"))
        == "plant-a | PEAT Configuration | Parseus"
    )


def test_peat_config_form_title_for_create_vs_update():
    assert (
        _render_title("peat/peatconfig_form.html")
        == "Upload PEAT Configuration | Parseus"
    )
    assert (
        _render_title("peat/peatconfig_form.html", object=_obj(name="plant-a"))
        == "Update plant-a | Parseus"
    )


def test_peat_device_form_title_for_create_vs_update():
    assert _render_title("peat/peatdevice_form.html") == "PEAT Host Details | Parseus"
    assert (
        _render_title("peat/peatdevice_form.html", object=_obj(label="plc-1"))
        == "Update plc-1 | Parseus"
    )


def test_peat_run_details_title_falls_back_to_run_dir():
    assert (
        _render_title("peat/run_details.html", object=_obj(name="", run_dir="run_7"))
        == "run_7 | PEAT Run | Parseus"
    )
    assert (
        _render_title("peat/run_details.html", object=_obj(name="Nightly", run_dir="r"))
        == "Nightly | PEAT Run | Parseus"
    )


def test_every_page_extending_base_declares_a_title_unless_exempt():
    """Guard: a new page that forgets the title block silently shows bare 'Parseus'."""
    exempt = {"home.html"}  # the landing page is the site name itself
    missing = []
    for path in WEBAPP.glob("*/templates/**/*.html"):
        text = path.read_text(encoding="utf-8")
        if '{% extends "base.html" %}' not in text:
            continue
        if path.name in exempt:
            continue
        if "{% block title %}" not in text:
            missing.append(str(path.relative_to(WEBAPP)))
    assert not missing, f"templates extending base.html without a title block: {missing}"
