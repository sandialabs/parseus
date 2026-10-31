"""
Abstraction layer over configuration handling.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from parseus.analytics.registry import AnalyticRegistryError, get_analytic_spec


@dataclass
class AnalyticConfiguration:
    """Configuration information for training and running an analytic."""

    name: str = ""
    fit_idx: str = ""
    fit_start: str = ""
    fit_end: str = ""
    run_idx: str = ""
    run_start: str = ""
    run_end: str = ""
    out_idx: str = ""
    init_args: Dict = None
    user_save: str = ""
    ip_filter: str = ""
    schedule: int = 0
    pull_duration: int = 0
    suppression: str = "0s"
    datastore_host_url: str = ""
    tags: List = None


def _index_name(index_cfg: dict, default: str = "") -> str:
    return dict(index_cfg or {}).get("index_name", default)


def get_analytic_config(
    user_input: Optional[Dict],
    analytic_name: str,
) -> AnalyticConfiguration:
    """Build an AnalyticConfiguration from the registered analytic spec.

    The registered AnalyticSpec supplies analytic defaults. Runtime/user/DB input
    supplies deployment overrides.
    """
    try:
        spec = get_analytic_spec(analytic_name)
    except AnalyticRegistryError as exc:
        raise KeyError(f"Analytic {analytic_name!r} is not registered") from exc

    user_input = user_input or {}
    conf = AnalyticConfiguration()
    conf.name = analytic_name

    fit_idx_cfg = dict(spec.fit_idx or {})
    run_idx_cfg = dict(spec.run_idx or {})
    out_idx_cfg = dict(spec.out_idx or {"index_name": f"{analytic_name}-out"})

    conf.fit_idx = user_input.get("fit_idx", {}).get(
        "index_name",
        _index_name(fit_idx_cfg),
    )
    conf.run_idx = user_input.get("run_idx", {}).get(
        "index_name",
        _index_name(run_idx_cfg),
    )
    conf.out_idx = user_input.get("out_idx", {}).get(
        "index_name",
        _index_name(out_idx_cfg, f"{analytic_name}-out"),
    )

    conf.fit_start = user_input.get("fit_start", fit_idx_cfg.get("start"))
    conf.fit_end = user_input.get("fit_end", fit_idx_cfg.get("end"))
    conf.run_start = user_input.get("run_start", run_idx_cfg.get("start"))
    conf.run_end = user_input.get("run_end", run_idx_cfg.get("end"))

    conf.init_args = user_input.get("init_args", dict(spec.init_args or {}))

    conf.user_save = user_input.get("user_save", "")
    conf.ip_filter = user_input.get("ip_filter", "")

    conf.schedule = int(user_input.get("schedule", spec.schedule or 0))
    conf.pull_duration = int(
        user_input.get("pull_duration", spec.pull_duration or 0)
    )

    # If you add `suppression` as a first-class AnalyticSpec field, use that.
    default_suppression = getattr(spec, "suppression", "0s")
    conf.suppression = str(
        user_input.get("suppression", default_suppression) or "0s"
    )

    datastore_override = user_input.get("ds_host_url")
    if datastore_override is not None:
        conf.datastore_host_url = getattr(datastore_override, "url", datastore_override)

    tags = list(spec.tags or [])
    out_idx_tags = out_idx_cfg.get("tags", [])
    if isinstance(out_idx_tags, str):
        out_idx_tags = [out_idx_tags]
    tags.extend(out_idx_tags)

    user_tag = user_input.get("out_idx", {}).get("tags")
    if user_tag is not None:
        if isinstance(user_tag, list):
            tags.extend(user_tag)
        else:
            tags.append(user_tag)

    conf.tags = sorted(set(tags))

    return conf
