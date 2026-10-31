"""Database-backed artifact storage for the analytics GUI.

The Django UI stores trained-analytic artifacts in the database rather than on
disk: the binary state blob lives in ``TrainedModel.artifact`` and the plaintext
manifest in ``TrainedModel.manifest``. This removes the need for a shared media
volume mount between the web and worker containers, and lets an operator inspect
an artifact's manifest directly in the Django admin.

The engine core stays DB-free and uses
:class:`~parseus.analytics.persistence.FileArtifactStore`; this backend is the
Django counterpart, sharing the same manifest/state split.
"""

from __future__ import annotations

from typing import Any, Dict

from parseus.analytics.persistence import (
    ArtifactNotFoundError,
    ArtifactStore,
    build_manifest,
    dump_state_bytes,
    load_state_bytes,
    validate_manifest,
)

from .models import TrainedModel


class DbArtifactStore(ArtifactStore):
    """Store trained-analytic artifacts in ``TrainedModel`` rows.

    The ``key`` is the ``TrainedModel`` primary key. :meth:`build_fields` is
    provided for the create-row path, where the row does not yet exist: it
    returns the ``artifact``/``manifest`` field values to set on a new instance
    within the same transaction that writes its other columns.
    """

    def build_fields(
        self, state: Dict[str, Any], *, analytic_class: str
    ) -> Dict[str, Any]:
        """Return the ``artifact``/``manifest`` field values for a new row."""
        manifest = build_manifest(analytic_class)
        return {"artifact": dump_state_bytes(state), "manifest": manifest}

    def save(self, key: str, state: Dict[str, Any], *, analytic_class: str) -> Dict[str, Any]:
        fields = self.build_fields(state, analytic_class=analytic_class)
        updated = TrainedModel.objects.filter(pk=key).update(
            artifact=fields["artifact"], manifest=fields["manifest"]
        )
        if not updated:
            raise ArtifactNotFoundError(f"No TrainedModel with pk {key!r}.")
        return fields["manifest"]

    def _get(self, key: str) -> TrainedModel:
        try:
            return TrainedModel.objects.get(pk=key)
        except TrainedModel.DoesNotExist as exc:
            raise ArtifactNotFoundError(f"No TrainedModel with pk {key!r}.") from exc

    def load(self, key: str) -> Dict[str, Any]:
        row = self._get(key)
        validate_manifest(row.manifest)
        return load_state_bytes(bytes(row.artifact))

    def load_from_instance(self, row: TrainedModel) -> Dict[str, Any]:
        """Load state directly from an already-fetched ``TrainedModel`` row."""
        validate_manifest(row.manifest)
        return load_state_bytes(bytes(row.artifact))

    def load_manifest(self, key: str) -> Dict[str, Any]:
        return self._get(key).manifest

    def exists(self, key: str) -> bool:
        return TrainedModel.objects.filter(pk=key).exists()

    def delete(self, key: str) -> None:
        TrainedModel.objects.filter(pk=key).delete()
