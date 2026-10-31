"""Versioned, self-describing persistence for trained analytics.

A trained analytic artifact has two logical parts:

``manifest``
    Small, JSON-friendly metadata describing the artifact: a monotonically
    increasing :data:`ARTIFACT_SCHEMA_VERSION`, the fully-qualified analytic
    class the state was produced by, the Parseus version that wrote it, and a
    UTC creation timestamp. The manifest is stored as **plaintext** (a
    ``manifest.json`` sidecar on the filesystem, a ``JSONField`` in the
    database) so an operator can see *what / when / which version* an artifact
    is **without deserializing** — and so a reader can validate an artifact
    before trusting it.

``state``
    The analytic's learned state, produced by
    :meth:`Analytic.state_dict <parseus.analytics.core.analytic.Analytic.state_dict>`
    and consumed by
    :meth:`Analytic.load_state_dict <parseus.analytics.core.analytic.Analytic.load_state_dict>`.
    It is dominated by NumPy arrays and scikit-learn estimators, so it is
    serialised as an opaque **binary** joblib blob rather than JSON.

.. warning::
    The state blob is a joblib (pickle) stream and therefore executes code on
    load. The manifest gates *validity and versioning*, **not** tampering. A
    restricted unpickler / signed artifact is a separate, future hardening step.

Storage location is decoupled from format via :class:`ArtifactStore`: the
engine core uses the DB-free :class:`FileArtifactStore`; the Django GUI provides
its own database-backed store. Both share the manifest/state split and the
byte-level helpers here.
"""

from __future__ import annotations

import io
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict

import joblib

# Bump this whenever the payload layout changes in a way a reader must know
# about. Readers reject an artifact whose schema version they do not understand
# rather than silently mis-restoring it.
ARTIFACT_SCHEMA_VERSION = 1


class ArtifactError(Exception):
    """Base class for problems reading or writing an analytic artifact."""


class ArtifactFormatError(ArtifactError):
    """Raised when an artifact's manifest or state is malformed."""


class ArtifactVersionError(ArtifactError):
    """Raised when an artifact's schema version is not understood by this reader."""


class ArtifactNotFoundError(ArtifactError):
    """Raised when a store is asked to load an artifact that does not exist."""


def _parseus_version() -> str:
    """Return the installed Parseus version, or ``"unknown"`` if undeterminable."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("parseus")
        except PackageNotFoundError:
            return "unknown"
    except Exception:  # pragma: no cover - importlib.metadata always present on 3.11+
        return "unknown"


def build_manifest(analytic_class: str) -> Dict[str, Any]:
    """Return a manifest for a freshly written artifact.

    :param analytic_class: Fully-qualified ``module.QualName`` of the analytic
                           whose state is being saved.
    """
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "analytic_class": analytic_class,
        "parseus_version": _parseus_version(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_manifest(manifest: Any) -> Dict[str, Any]:
    """Validate a manifest mapping and return it.

    :raises ArtifactFormatError: If ``manifest`` is not a mapping.
    :raises ArtifactVersionError: If its schema version is not understood.
    """
    if not isinstance(manifest, dict):
        raise ArtifactFormatError(
            f"Artifact manifest must be a mapping, got {type(manifest).__name__}."
        )
    schema_version = manifest.get("schema_version")
    if schema_version != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactVersionError(
            f"Artifact schema version {schema_version!r}; this build understands "
            f"version {ARTIFACT_SCHEMA_VERSION}."
        )
    return manifest


# ---------------------------------------------------------------------------
# State (binary joblib) byte-level helpers
# ---------------------------------------------------------------------------


def dump_state_bytes(state: Dict[str, Any]) -> bytes:
    """Serialise an analytic ``state`` mapping to an opaque joblib byte blob."""
    buffer = io.BytesIO()
    joblib.dump(state, buffer)
    return buffer.getvalue()


def load_state_bytes(blob: bytes) -> Dict[str, Any]:
    """Deserialise a joblib state blob produced by :func:`dump_state_bytes`.

    :raises ArtifactFormatError: If the blob does not deserialise to a mapping.
    """
    state = joblib.load(io.BytesIO(blob))
    if not isinstance(state, dict):
        raise ArtifactFormatError(
            f"Artifact state must be a mapping, got {type(state).__name__}."
        )
    return state


# ---------------------------------------------------------------------------
# Pluggable storage backend
# ---------------------------------------------------------------------------


class ArtifactStore(ABC):
    """A place trained-analytic artifacts are saved to and loaded from.

    Implementations decouple *where* an artifact lives (filesystem, database,
    object store) from its *format* (a plaintext manifest plus a binary state
    blob). Callers depend on this interface rather than branching on storage.
    """

    @abstractmethod
    def save(self, key: str, state: Dict[str, Any], *, analytic_class: str) -> Dict[str, Any]:
        """Persist ``state`` under ``key`` and return the manifest that was written."""

    @abstractmethod
    def load(self, key: str) -> Dict[str, Any]:
        """Return the state mapping stored under ``key``.

        :raises ArtifactNotFoundError: If no artifact exists for ``key``.
        :raises ArtifactVersionError: If the manifest schema version is not understood.
        """

    @abstractmethod
    def load_manifest(self, key: str) -> Dict[str, Any]:
        """Return the plaintext manifest for ``key`` without loading the state.

        :raises ArtifactNotFoundError: If no artifact exists for ``key``.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an artifact is stored under ``key``."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the artifact stored under ``key``, if any."""


class FileArtifactStore(ArtifactStore):
    """Filesystem artifact store used by the DB-free engine core.

    Each artifact is a pair of sibling files under ``root``:

    - ``{key}.joblib`` — the binary state blob;
    - ``{key}.manifest.json`` — the plaintext manifest.

    Keeping the manifest as a readable sidecar lets an operator inspect an
    artifact on disk without deserialising the (executable) state blob.
    """

    STATE_SUFFIX = ".joblib"
    MANIFEST_SUFFIX = ".manifest.json"

    def __init__(self, root: str | os.PathLike):
        self.root = str(root)

    def _state_path(self, key: str) -> str:
        return os.path.join(self.root, f"{key}{self.STATE_SUFFIX}")

    def _manifest_path(self, key: str) -> str:
        return os.path.join(self.root, f"{key}{self.MANIFEST_SUFFIX}")

    def save(self, key: str, state: Dict[str, Any], *, analytic_class: str) -> Dict[str, Any]:
        os.makedirs(self.root, exist_ok=True)
        manifest = build_manifest(analytic_class)
        joblib.dump(state, self._state_path(key))
        with open(self._manifest_path(key), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
        return manifest

    def load(self, key: str) -> Dict[str, Any]:
        if not self.exists(key):
            raise ArtifactNotFoundError(f"No artifact for key {key!r} under {self.root!r}.")
        validate_manifest(self.load_manifest(key))
        state = joblib.load(self._state_path(key))
        if not isinstance(state, dict):
            raise ArtifactFormatError(
                f"Artifact state for {key!r} must be a mapping, got {type(state).__name__}."
            )
        return state

    def load_manifest(self, key: str) -> Dict[str, Any]:
        manifest_path = self._manifest_path(key)
        if not os.path.isfile(manifest_path):
            raise ArtifactNotFoundError(
                f"No manifest for key {key!r} under {self.root!r}."
            )
        with open(manifest_path, encoding="utf-8") as fh:
            return json.load(fh)

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._state_path(key)) and os.path.isfile(
            self._manifest_path(key)
        )

    def delete(self, key: str) -> None:
        for path in (self._state_path(key), self._manifest_path(key)):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def _store_and_key_for_path(file_path: str) -> tuple["FileArtifactStore", str]:
    """Map a ``foo/bar.joblib`` path to a ``(FileArtifactStore(foo), "bar")`` pair.

    Lets the path-based :meth:`Analytic.save`/:meth:`Analytic.load` convenience
    API route through a :class:`FileArtifactStore` (writing the manifest sidecar
    alongside the state blob) without callers needing to construct a store.
    """
    directory = os.path.dirname(file_path) or "."
    filename = os.path.basename(file_path)
    if filename.endswith(FileArtifactStore.STATE_SUFFIX):
        key = filename[: -len(FileArtifactStore.STATE_SUFFIX)]
    else:
        key = os.path.splitext(filename)[0]
    return FileArtifactStore(directory), key


def save_state_to_path(file_path: str, state: Dict[str, Any], *, analytic_class: str) -> None:
    """Save ``state`` to a filesystem path via a :class:`FileArtifactStore`."""
    store, key = _store_and_key_for_path(file_path)
    store.save(key, state, analytic_class=analytic_class)


def load_state_from_path(file_path: str) -> Dict[str, Any]:
    """Load an analytic state mapping from a filesystem path."""
    store, key = _store_and_key_for_path(file_path)
    return store.load(key)
