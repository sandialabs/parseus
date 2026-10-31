"""Tests for operator-supplied analytic rules (config and/or UI).

Rules an analytic accepts (allow-lists) can come from deployment **config**
(the analytic's ``init_args``) and/or an external source such as the UI. These
pin that:

    1. config-supplied rules reach the analytic's runtime attribute;
    2. config rules and fetched rules **compose** (config preserved, fetched
       appended) via :class:`OperatorRuleMixin`;
    3. the mixin is source-neutral and reusable by declaration.
"""

from __future__ import annotations

from parseus.analytics.core import Analytic
from parseus.analytics.core.operator_rules import OperatorRuleMixin
from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)


def test_config_supplied_rules_reach_the_analytic():
    # Rules passed via init_args (i.e. from config) land on the runtime attr.
    analytic = SysmonUnapprovedIpAnalytic(ip_rules=[{"name": "from-config"}])
    assert analytic.ip_rules_ == [{"name": "from-config"}]


def test_merge_rules_composes_config_and_fetched_rules():
    # init_args already carries a config rule; fetched (e.g. UI) rules append.
    init_args = {"ip_rules": [{"name": "from-config"}]}
    merged = SysmonUnapprovedIpAnalytic.merge_rules(
        init_args, [{"name": "from-ui"}]
    )
    assert merged["ip_rules"] == [{"name": "from-config"}, {"name": "from-ui"}]
    # Original is not mutated.
    assert init_args["ip_rules"] == [{"name": "from-config"}]


def test_merge_rules_noop_without_fetched_rules():
    init_args = {"ip_rules": [{"name": "from-config"}]}
    assert SysmonUnapprovedIpAnalytic.merge_rules(init_args, []) == init_args


def test_mixin_is_source_neutral_and_reusable():
    # Any analytic can reuse the mechanism by declaring the two attributes —
    # nothing here is Sysmon-specific.
    class _RuleUsingAnalytic(OperatorRuleMixin, Analytic):
        _rule_arg = "allow_values"
        _rule_state_attr = "allow_values_"

        def __init__(self, allow_values=None, **kwargs):
            super().__init__(pull_duration=1, **kwargs)
            self.allow_values_ = allow_values or []

        def _run(self, start, end, transformed_documents, state, **other_documents):
            return []

    merged = _RuleUsingAnalytic.merge_rules({}, ["v1", "v2"])
    assert merged["allow_values"] == ["v1", "v2"]

    analytic = _RuleUsingAnalytic(**merged)
    # After a "reload", apply_rule_state re-applies from init_args.
    analytic.allow_values_ = []
    analytic.apply_rule_state(merged)
    assert analytic.allow_values_ == ["v1", "v2"]
