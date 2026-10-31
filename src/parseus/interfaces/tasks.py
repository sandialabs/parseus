"""Task to run and push analytics to ElasticSearch"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Type

from parseus.analytics.base import Analytic
from parseus.analytics.persistence import FileArtifactStore
from parseus.interfaces.common import fit, get_ds_client, run
from parseus.interfaces.config import get_analytic_config

LOGGER = logging.getLogger("parseus")

# Index template that pins the field types the alerts UI relies on, applied to
# every index that feeds the "alerts-*" view pattern. Without it, each daily
# alerts index is dynamically mapped from its first document, so field types can
# drift between days (a ``.keyword`` subfield present on one day and absent the
# next, ``handled`` unmapped on a day whose first alert omitted it, etc.),
# making the exact-term / boolean / script-sort queries behave inconsistently or
# fail a shard. ``text`` + ``keyword`` subfield preserves both the analyzed and
# exact-match (``.keyword``) query paths the code uses.
ALERTS_INDEX_TEMPLATE_NAME = "parseus-alerts"
ALERTS_INDEX_PATTERNS = ["alerts-*"]
_TEXT_WITH_KEYWORD = {
    "type": "text",
    "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}},
}
ALERTS_INDEX_MAPPINGS = {
    "properties": {
        "@timestamp": {"type": "date"},
        "handled": {"type": "boolean"},
        "agent": {"properties": {"type": _TEXT_WITH_KEYWORD}},
        "event": {"properties": {"uuid": _TEXT_WITH_KEYWORD}},
        "acknowledge": {
            "properties": {
                "reason": _TEXT_WITH_KEYWORD,
                "timestamp": {"type": "date"},
            }
        },
    }
}


def ensure_alerts_index_template(datastore=None) -> bool:
    """Idempotently install the ``alerts-*`` index template.

    Best-effort: logs and returns ``False`` on failure rather than raising, so a
    template problem never blocks an alert write. Safe to call repeatedly.
    """
    datastore = datastore or get_ds_client()
    return datastore.ensure_index_template(
        ALERTS_INDEX_TEMPLATE_NAME,
        ALERTS_INDEX_PATTERNS,
        ALERTS_INDEX_MAPPINGS,
    )


def _fetch_operator_rules(analytic_name: str) -> list:
    """Return UI-managed Sysmon rules for an analytic class, or an empty list.

    The rules live in the optional ``alerts`` Django app; when it is not
    available (e.g. the DB-free engine without that app installed) this returns
    no rules rather than failing.
    """
    class_name = str(analytic_name or "").split(".")[-1]
    try:
        from parseus.webapp.alerts.models import get_sysmon_rules_for_analytic_class
    except Exception:
        return []
    return get_sysmon_rules_for_analytic_class(class_name) or []


def run_and_push_analytics(analytic: Type[Analytic], user_input=None):
    """
    Run analytic and push alerts using the analytic's descriptor defaults,
    layered with any DB/user overrides in ``user_input``.
    """
    analytic_config = get_analytic_config(
        user_input=user_input,
        analytic_name=analytic.__name__,
    )
    init_args = dict(analytic_config.init_args or {})
    rules = _fetch_operator_rules(analytic.__name__)
    if rules and hasattr(analytic, "merge_rules"):
        init_args = analytic.merge_rules(init_args, rules)
    init_args.setdefault("suppression", analytic_config.suppression)
    loaded_analytic = analytic(**init_args)

    datastore = get_ds_client()
    artifact_store = get_scheduled_artifact_store()
    artifact_key = f"{analytic.__name__}_celery"
    if artifact_store.exists(artifact_key):
        loaded_analytic.load_state_dict(artifact_store.load(artifact_key))
        if hasattr(loaded_analytic, "apply_rule_state"):
            loaded_analytic.apply_rule_state(init_args)
    elif loaded_analytic.requires_fit():
        loaded_analytic = fit(
            ds_client=datastore,
            analytic=loaded_analytic,
            analytic_config=analytic_config,
        )

    # Load persisted run-to-run state (suppression memory, dedup marks) so it
    # survives across scheduled runs. Kept in its own artifact, separate from the
    # immutable trained model.
    state_key = f"{artifact_key}.state"
    state_before = _load_scheduled_state(artifact_store, state_key)
    loaded_analytic.import_state(state_before)

    alerts = run(
        ds_client=datastore,
        analytic=loaded_analytic,
        analytic_config=analytic_config,
    )

    # Save the run-to-run state back only when it actually changed, so a run that
    # evolves no state does not rewrite the artifact.
    state_after = loaded_analytic.export_state()
    if state_after != state_before:
        artifact_store.save(
            state_key, state_after, analytic_class=loaded_analytic.class_name
        )

    push_alerts(analytic_config, alerts)


def _load_scheduled_state(artifact_store, state_key: str) -> dict:
    """Return the persisted run-to-run state for ``state_key``, or ``{}``.

    A missing artifact (first run) yields an empty mapping. A corrupt or
    unreadable state artifact must not take down the run: it is logged and
    treated as empty so the analytic starts from a clean state rather than
    crashing the scheduled task.
    """
    if not artifact_store.exists(state_key):
        return {}
    try:
        return artifact_store.load(state_key)
    except Exception:  # noqa: BLE001 - defensive: never fail a run over state I/O
        LOGGER.exception("Could not load run-to-run state %r; starting empty.", state_key)
        return {}


def get_scheduled_artifact_store() -> FileArtifactStore:
    """Return the file-backed artifact store for scheduled (celery) runs.

    The scheduled runner is part of the DB-free engine, so it loads trained
    artifacts from the filesystem rather than the database. Artifacts are keyed
    ``{AnalyticName}_celery``.
    """
    storage_dir = Path.home() / ".parseus" / "artifacts" / "media" / "models"
    return FileArtifactStore(storage_dir)


def _output_index_name(analytic_config) -> str:
    """Return the configured output index, supporting config and UI objects."""
    return (
        getattr(analytic_config, "out_idx", None)
        or getattr(analytic_config, "out_idx_name", None)
        or "alerts"
    )


def push_alerts(analytic_config, alerts) -> int:
    """Push alert documents to the configured output index and return the count."""
    alerts = list(alerts or [])
    if not alerts:
        LOGGER.info("No alerts to push.")
        return 0

    for index, alert in enumerate(alerts):
        if not isinstance(alert, dict):
            raise TypeError(
                f"Alert #{index} must be a dictionary, got {type(alert).__name__}."
            )

    base_index = _output_index_name(analytic_config)
    date_suffix = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    out_index_name = f"{base_index}-{date_suffix}"
    datastore = get_ds_client()

    # Make sure the alerts-* mapping template is in place before the first write
    # creates today's index dynamically, so its fields are pinned (not drifted).
    ensure_alerts_index_template(datastore)

    for alert in alerts:
        datastore.index(index=out_index_name, document=alert)

    LOGGER.info("Pushed %s alerts to index '%s'.", len(alerts), out_index_name)
    return len(alerts)
