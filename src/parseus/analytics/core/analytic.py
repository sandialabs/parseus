"""The :class:`Analytic` runtime contract shared by every analytic."""

import abc
import logging
import types
import uuid
import warnings
from collections.abc import Iterable as IterableABC
from datetime import datetime, timezone
from os.path import isfile
from typing import Any, Dict, Iterable, Union

import pandas as pd

from parseus.analytics.core.alerts import build_ecs_alert
from parseus.analytics.core.state import StateStore
from parseus.analytics.core.suppression import DEFAULT_WINDOW
from parseus.util.datetime_utils import make_zulu_time
from parseus.util.numerical import robust_log_adjust

LOGGER = logging.getLogger("parseus.analytics")


class AnalyticContractError(ValueError):
    """Raised when an analytic violates the base runtime contract."""


class Analytic(abc.ABC):
    """
    Abstract base class for an analytic that can be run on the user's data.

    Concrete analytics implement the run contract by overriding the single
    abstract :meth:`_run`. Run-to-run state (values the analytic must remember
    between run windows and between scheduled runs) is carried
    by an explicit :class:`~parseus.analytics.core.state.StateStore` the runtime
    passes into :meth:`_run` — analytics must not stash run-to-run state on
    ``self``. Supervised analytics (``requires_fit() is True``) must also
    implement :meth:`_fit`.

    :param pull_duration: The number of seconds of data the analytic needs
                          to function correctly. For example,
        :code:`pull_duration == 5` means the analytic, would load 5 seconds' worth of data.
    :type pull_duration: int or float
    :param str suppression: The alert-suppression window for this analytic (a
        Prometheus-style duration such as ``"0s"``, ``"24h"``, or ``"infinite"``).
        This is **not** ``pull_duration``: ``pull_duration`` sizes how much *input*
        data one run fetches, whereas ``suppression`` controls how often the same
        *finding* re-alerts across runs. The default ``"0s"`` never suppresses, so
        behaviour is unchanged until an operator sets a window. See
        :class:`~parseus.analytics.core.suppression.SuppressionWindow`.
    :param logging.Logger log: The logger to which to write logs. Many
                               analytics ignore this, but some may use it.
                               If None (default), the package logger is used.
    :param kwargs: Passed to the next constructor
    """

    def __init__(
        self,
        pull_duration: Union[int, float],
        log: logging.Logger = None,
        verbose=0,
        suppression: str = DEFAULT_WINDOW,
        **kwargs,
    ):
        # this will get updated by child analytics, but the default is no transformation
        self._transform = lambda x, **kw: x

        self._log = log or LOGGER

        self.load_window_ = pull_duration
        kwargs.setdefault("pull_duration", None)
        self.class_name = f"{type(self).__module__}.{type(self).__qualname__}"
        # Explicit run-to-run state, carried across run windows within a run and
        # persisted between scheduled runs. Analytics read/write this
        # via the ``state`` argument to :meth:`_run`, never by stashing on self.
        self._state = StateStore()
        # Per-analytic alert-suppression window. Distinct from ``pull_duration``
        # (see the class docstring). Analytics that emit repeatable findings gate
        # them with ``SuppressionWindow(state, self.suppression_)`` inside
        # :meth:`_run`; the default ``"0s"`` never suppresses.
        self.suppression_ = suppression

    def fit(self, *training_document_sets) -> None:
        """
        Trains an analytic on the given training data set(s)

        :param training_document_sets: A list of training sets (which themselves are
                                       lists/iterables of documents) to use to train
                                       the analytic
        """
        # transform it
        training_documents = [
            self._transform(
                x, start=None, end=None, **self._get_transform_parameters(True)
            )
            for x in training_document_sets
        ]
        self._fit(*training_documents)

    def _fit(self, *transformed_document_sets) -> None:
        """
        When overridden in a derived class, trains an analytic with the given training data set(s)

        :param transformed_document_sets: A list of training sets (which themselves are
                                          lists/iterables of documents) to train the analytic,
                                          already transformed with self._transform_pipeline
        """
        if self.requires_fit():
            raise NotImplementedError(
                f"{self.__class__.__name__} requires fit but does not implement _fit."
            )

    def data_source(self):
        """Return this analytic's data-source specification.

        This is the authoritative source of the analytic's query intent (index
        type plus per-phase query/aggregation/return-field selection) at
        runtime. The default returns the :class:`DataSource` declared on the
        ``@register_analytic`` descriptor; analytics whose query depends on
        instance configuration (e.g. a configurable aggregation interval)
        override this to build the specification from their own state.

        :return: The declared :class:`DataSource` capability, or ``None`` when
                 the analytic class is not registered with a descriptor.
        """
        from parseus.analytics.registry import find_spec_for_class

        spec = find_spec_for_class(type(self))
        return spec.data_source if spec else None

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        ML analytics will use :code:`requires_fit == True`, but other analytics may vary
        """
        return True

    def _verify_dependencies(self, other_data_or_sources: Dict[str, Any]) -> None:
        """
        Verifies given dependencies match dependencies expected by analytic

        :param dict other_data_or_sources: The dependencies that were given
                                           to the analytic when called
        :raises ValueError: When the dependencies are mismatched (either the user
                            was missing one or specified an extra one)
        """
        true_dependencies = set(self.dependencies().keys())
        for dep_name in true_dependencies:
            if dep_name not in other_data_or_sources:
                raise ValueError(f"Missing data source for dependency '{dep_name}'.")
        for dep_name in other_data_or_sources:
            if dep_name not in true_dependencies:
                raise ValueError(f"Unknown dependency '{dep_name}'.")

    def _get_transform_parameters(self, fitting: bool) -> Dict[str, Any]:
        """
        Gets a dictionary of parameters to be passed to the transform methods

        :param bool fitting: True if the analytic is fitting, False if it is running
        :return: A dictionary of parameters for the transformation methods
        """
        # this could be implemented in a child class
        return {}

    def run_on_data(
        self,
        documents: Iterable[dict],
        start: datetime,
        end: datetime,
        **other_documents,
    ) -> Iterable[dict]:
        """
        Runs the analytic on the given list of documents and time window while
        managing stateful properties of the analytic

        :param iterable documents: A single list of documents to run the analytic on
        :param datetime start: The start timestamp of the capture
        :param datetime end: The end timestamp of the capture
        :param other_documents: Dictionary of additional document lists from outputs
                                of the dependencies. Format: dep_name => [list of docs]
        :return: The analytic results
        """
        # make sure all dependencies are met exactly
        self._verify_dependencies(other_documents)
        # run the analytic
        transformed_documents = self._transform(
            documents, start=start, end=end, **self._get_transform_parameters(False)
        )
        alerts = self._run(
            start, end, transformed_documents, self._state, **other_documents
        )
        return self.add_common_fields_to_alerts(alerts)

    def save(self, file_path: str) -> None:
        """
        Saves the analytic model to a file. This is only useful when the analytic
        has some component of training (e.g. you have called fit())

        The artifact is a versioned, self-describing joblib file with a
        plaintext ``.manifest.json`` sidecar (see
        :mod:`parseus.analytics.persistence`).

        :param str file_path: The path to which to save the analytic

        >>> analytic.save("analytic.joblib")

        """
        from parseus.analytics.persistence import save_state_to_path

        save_state_to_path(file_path, self.state_dict(), analytic_class=self.class_name)

    def load(self, file_path: str) -> None:
        """
        Loads a saved analytic from a file

        :param str file_path: The file from which to load the analytic

        .. code-block:: python

            # analytic has already been instantiated from the proper Analytic class
            analytic.load("analytic.joblib")

        """
        from parseus.analytics.persistence import load_state_from_path

        self.load_state_dict(load_state_from_path(file_path))

    @property
    def _save_fields(self) -> set:
        """
        Gets a list of fields that will be saved into the analytic's saved model file
        """
        return {item for item in dir(self) if item[-1] == "_" and item[-2:] != "__"}

    def state_dict(self) -> dict:
        """Return this analytic's trained-model state as a plain mapping.

        The returned dict contains the analytic's instance attributes with
        anything that cannot be meaningfully serialised (bound functions,
        loggers, log handlers) stripped out. It is the payload written to the
        (immutable, fit-time) model artifact by :meth:`save`.

        The run-to-run :class:`StateStore` (``self._state``) is intentionally
        **excluded** here: it evolves every run and is persisted separately via
        :meth:`export_state` / :meth:`import_state`, so the model artifact stays
        immutable after fit.
        """
        # pylint: disable=access-member-before-definition
        to_save = dict(self.__dict__)
        # Run-to-run state is persisted separately (see export_state); keep it
        # out of the trained-model artifact.
        to_save.pop("_state", None)
        # drop attributes we know cannot (or should not) be serialised
        for key, value in list(to_save.items()):
            if isinstance(value, (types.FunctionType, logging.Logger, logging.Handler)):
                if key not in ("_transform", "_log", "_log_listener"):
                    # this is an attribute that we don't know about,
                    # so warn the caller before dropping it
                    warnings.warn(f"Cannot serialise {key}. Skipping.")
                to_save.pop(key)
        return to_save

    def load_state_dict(self, state: dict) -> None:
        """Restore this analytic's state from a mapping produced by :meth:`state_dict`.

        :param dict state: The state mapping to apply.
        """
        # pylint: disable=attribute-defined-outside-init, access-member-before-definition
        from parseus.analytics.core.models import Model

        self.__dict__.update(
            {
                k: v
                for k, v in state.items()
                if k in self._save_fields or k not in vars(self)
            }
        )
        for key, value in self.__dict__.items():
            if isinstance(value, Model):
                if self.__dict__.get("_log", None):
                    self.__dict__.get(key).logger = self._log

    def __getstate__(self):
        """Object-protocol hook (e.g. ``copy.deepcopy``); delegates to :meth:`state_dict`."""
        return self.state_dict()

    def __setstate__(self, state):
        """Object-protocol hook; delegates to :meth:`load_state_dict`."""
        self.load_state_dict(state)

    def export_state(self) -> dict:
        """Return this analytic's run-to-run state as a serialisable mapping.

        This is the *run-to-run* :class:`StateStore` (suppression memory, dedup
        marks, baseline flags) — **not** the trained model, which
        :meth:`state_dict` covers. The runtime persists the two separately: the
        model artifact is written once at fit time and is immutable, while this
        state evolves each run and is saved back after every run. Round-trips
        through :meth:`import_state`.
        """
        return self._state.as_dict()

    def import_state(self, state: dict) -> None:
        """Restore this analytic's run-to-run state from :meth:`export_state`.

        :param dict state: The state mapping to load (a fresh empty store is
                           used when ``state`` is falsy).
        """
        self._state = StateStore.from_dict(state or {})


    def fit_or_load(self, model_file_path: str, *training_document_sets) -> None:
        """
        Attempts to load a fitted model from a file, but if it doesn't exist,
        fits it and saves it

        :param str model_file_path: The file path to load the model from or save it to
        :param training_document_sets: The list of training data sets to fit the model
                                       on (if needed), or a list of callbacks to obtain
                                       the training data. The latter is useful for lazy
                                       evaluation, so the data may not need to be
                                       fetched unless necessary
        """
        if isfile(model_file_path):
            # it has already been trained
            self.load(model_file_path)
        else:
            if self.requires_fit():
                # we need to train it
                training_document_sets = list(training_document_sets)
                for i, item in enumerate(training_document_sets):
                    if callable(item):
                        training_document_sets[i] = item()
                self.fit(*training_document_sets)

            # save it
            self.save(model_file_path)

    @classmethod
    def dependencies(
        cls,
    ) -> Dict[str, Any]:  # the "Any" here is really an analytic class variable
        """
        Returns this analytic's dependencies on the results of other analytics

        :return: A dictionary of (dependency name => analytic class), where the
                 dependency name and analytic results are passed into run() as
                 keyword arguments
        """
        return {}

    @abc.abstractmethod
    def _run(
        self,
        start: datetime,
        end: datetime,
        transformed_documents: Iterable[dict],
        state: "StateStore",
        **other_documents,
    ) -> Iterable[dict]:
        """Run the analytic on one window of data and return alert dicts.

        This is the single method every concrete analytic must implement.

        :param datetime start: The timestamp of the start of the data subset.
        :param datetime end: The timestamp of the end of the data subset.
        :param iterable transformed_documents: The documents to analyse
                                               (of duration ``pull_duration``),
                                               already passed through
                                               ``self._transform``.
        :param StateStore state: Run-to-run state for this analytic. Read and
                                 write it for anything that must be remembered
                                 across run windows (e.g. a "baseline emitted"
                                 flag, or already-raised alert keys). Do not keep
                                 run-to-run state on ``self``.
        :param other_documents: Additional document lists from the outputs of
                                this analytic's dependencies
                                (``dep_name => [list of docs]``).
        :return: An iterable of alert dictionaries.
        """
        raise NotImplementedError

    def _logic_results_to_documents(self, logic_results: pd.Series):
        return [
            build_ecs_alert(
                action="information",
                original=None,
                riskscore=score,
                timestamp=make_zulu_time(time),
            )
            for time, score in zip(
                logic_results.index, robust_log_adjust(logic_results.values)
            )
        ]

    def _normalize_alerts(self, alerts) -> list[dict]:
        """Return alerts as a list and verify each alert is a dictionary."""
        if alerts is None:
            raise AnalyticContractError(
                f"{self.__class__.__name__}._run returned None; expected an "
                "iterable of alert dictionaries. Return [] when there are no alerts."
            )
        if isinstance(alerts, dict):
            raise AnalyticContractError(
                f"{self.__class__.__name__}._run returned a single dictionary; "
                "expected an iterable of alert dictionaries."
            )
        if not isinstance(alerts, IterableABC):
            raise AnalyticContractError(
                f"{self.__class__.__name__}._run returned {type(alerts).__name__}; "
                "expected an iterable of alert dictionaries."
            )

        normalized_alerts = list(alerts)
        for index, alert in enumerate(normalized_alerts):
            if not isinstance(alert, dict):
                raise AnalyticContractError(
                    f"{self.__class__.__name__}._run returned alert #{index} as "
                    f"{type(alert).__name__}; expected dict."
                )
        return normalized_alerts

    def add_common_fields_to_alerts(self, alerts):
        """
        Stamp fields common to most analytics onto each alert and return them.

        Alerts are enriched in place — this runs on the analytic's own freshly
        produced alert dicts at the end of :meth:`run_on_data`. The method is
        idempotent: existing values are preserved with ``setdefault`` so repeated
        calls never replace an event UUID or timestamp (some legacy analytics add
        common fields internally before their results pass back through here).

        Timestamps are timezone-aware UTC, matching the datastore's Zulu-time
        convention across the codebase.
        """
        now = datetime.now(timezone.utc)
        alerts = self._normalize_alerts(alerts)
        for alert in alerts:
            alert.setdefault("agent", {})
            alert["agent"].setdefault("type", self.__class__.__name__)

            alert.setdefault("acknowledge", {})
            alert["acknowledge"].setdefault("reason", "none")
            alert["acknowledge"].setdefault("timestamp", now)

            alert.setdefault("event", {})
            alert["event"].setdefault("created", now)
            alert["event"].setdefault("uuid", uuid.uuid4())

            # Defensive default: the alerts UI filters on a top-level boolean
            # ``handled`` field. Every built-in analytic sets ``handled=False``
            # explicitly, but stamping it here too guarantees an analytic that
            # forgets to cannot emit an alert that is silently invisible to the
            # operator (an unmapped/absent ``handled`` would not match the
            # ``{"term": {"handled": False}}`` filter).
            alert.setdefault("handled", False)
        return alerts
