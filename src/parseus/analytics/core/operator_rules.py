"""Shared operator-rule handling for analytics that take allow-list rules.

Some analytics accept operator-supplied rules (e.g. allow-lists: "permit this
value", "permit it only during these hours"). Those rules can come from more
than one place — a deployment **config** (the analytic's ``init_args``) and/or
the Django **UI** (the optional ``alerts`` app's rule table). This mixin is the
single, source-neutral seam for handling them, so the runtime does not hard-code
a per-analytic-class rule map.

An analytic that uses operator rules mixes this in and declares its binding:

- ``_rule_arg``: the constructor arg the rules are passed as (e.g. ``"ip_rules"``);
- ``_rule_state_attr``: the fitted attribute that holds them at runtime
  (e.g. ``"ip_rules_"``).

Rules from config and from the UI **compose**: config rules arrive in
``init_args[_rule_arg]`` at construction; :meth:`merge_rules` appends any
externally-fetched (e.g. UI) rules onto them. Two seams, because rules apply at
two moments:

- :meth:`merge_rules` (classmethod) runs **before construction**, folding fetched
  rules into the ``init_args`` mapping the analytic is built from.
- :meth:`apply_rule_state` runs **after** a saved artifact is loaded, to
  re-apply the rule attribute (and timezone) the load may have overwritten.

The mechanism is deliberately generic (not tied to any one analytic family): any
analytic with an operator-supplied rule list can reuse it by declaring the two
attributes.
"""

from __future__ import annotations

from typing import Any, Dict, List


class OperatorRuleMixin:
    """Per-analytic binding for operator-supplied allow-list rules.

    Subclasses set :attr:`_rule_arg` and :attr:`_rule_state_attr`. Rules may be
    supplied by config (via ``init_args``) and/or fetched from an external source
    (e.g. the UI) and merged in; the two compose.
    """

    _rule_arg: str = ""
    _rule_state_attr: str = ""

    @classmethod
    def merge_rules(
        cls, init_args: Dict[str, Any] | None, rules: List[Any]
    ) -> Dict[str, Any]:
        """Return ``init_args`` with ``rules`` appended to this analytic's rule arg.

        A copy is returned; the input is not mutated. Any rules already present in
        ``init_args[_rule_arg]`` (e.g. supplied by config) are preserved and the
        fetched ``rules`` are appended after them. When ``rules`` is empty or the
        analytic declares no rule arg, the args are returned unchanged.
        """
        next_init_args = dict(init_args or {})
        if not rules or not cls._rule_arg:
            return next_init_args
        next_init_args[cls._rule_arg] = [
            *next_init_args.get(cls._rule_arg, []),
            *rules,
        ]
        return next_init_args

    def apply_rule_state(self, init_args: Dict[str, Any]) -> None:
        """Re-apply the rule attribute (and timezone) from ``init_args``.

        Used after loading a saved artifact, whose stored state may not carry the
        current operator rules. Only sets what is present in ``init_args``.
        """
        if self._rule_state_attr and self._rule_arg in init_args:
            setattr(self, self._rule_state_attr, init_args[self._rule_arg])
        if "timezone" in init_args:
            self.default_timezone_ = init_args["timezone"]
