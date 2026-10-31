"""Explicit run-to-run state for analytics.

An analytic's *learned model* (fitted statistics, scikit-learn estimators) is
training-time artifact state and lives on the analytic instance. This module
covers the other, smaller kind of state: the values an analytic must remember
**between run windows** (and, once persisted, between scheduled runs) —
for example whether it has already emitted its one-time baseline alerts, or
which alerts it has already raised so it does not raise them again.

:class:`StateStore` makes that run-to-run state an explicit, named, serialisable
object that the runtime hands to :meth:`Analytic._run` rather than something
each analytic stashes on ``self`` under ad-hoc attribute names. Only values an
analytic explicitly writes here survive; the store round-trips through
:meth:`as_dict` / :meth:`from_dict` so :mod:`parseus.analytics.persistence` can
save and restore it.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Iterable, List


class StateStore:
    """A small, mutable, serialisable key/value holder for run-to-run state.

    The store is deliberately minimal: analytics read and write named keys, and
    the runtime serialises the whole thing via :meth:`as_dict`. Stored values
    must be plain, serialisable data (scalars, lists, dicts) so the persisted
    form is stable and human-readable — notably, ordered unique collections are
    kept as **lists** rather than Python ``set`` objects (see
    :meth:`add_unique`).
    """

    def __init__(self, initial: Dict[str, Any] | None = None) -> None:
        self._data: Dict[str, Any] = copy.deepcopy(dict(initial)) if initial else {}

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value stored under ``key``, or ``default`` if absent."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``."""
        self._data[key] = value

    def setdefault(self, key: str, factory: Callable[[], Any]) -> Any:
        """Return ``key``'s value, first initialising it via ``factory`` if absent.

        Unlike :meth:`dict.setdefault`, the default is produced lazily by
        calling ``factory`` so callers can pass e.g. ``list`` without building a
        throwaway object on every call.
        """
        if key not in self._data:
            self._data[key] = factory()
        return self._data[key]

    def add_unique(self, key: str, value: Any) -> bool:
        """Append ``value`` to the ordered, de-duplicated list stored at ``key``.

        The key is initialised to an empty list if absent. Returns ``True`` when
        ``value`` was newly added, ``False`` when it was already present. This is
        the list-based replacement for a ``set`` of "already handled" markers:
        it preserves insertion order and serialises cleanly.
        """
        collection: List[Any] = self.setdefault(key, list)
        if value in collection:
            return False
        collection.append(value)
        return True

    def contains(self, key: str, value: Any) -> bool:
        """Return whether ``value`` is in the list stored at ``key``."""
        collection = self._data.get(key)
        return bool(collection) and value in collection

    def update_unique(self, key: str, values: Iterable[Any]) -> None:
        """Append each of ``values`` to the ordered unique list at ``key``."""
        for value in values:
            self.add_unique(key, value)

    def as_dict(self) -> Dict[str, Any]:
        """Return a deep copy of the stored state for serialisation."""
        return copy.deepcopy(self._data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "StateStore":
        """Rebuild a :class:`StateStore` from a mapping produced by :meth:`as_dict`."""
        return cls(data)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"StateStore({self._data!r})"
