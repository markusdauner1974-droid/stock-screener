"""Generation-scoped reader facade for Economic Theme product payloads."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.economic_taxonomy_runtime import (
    GenerationInputManifest,
    ReaderSnapshotBundle,
    ReaderSnapshotEntry,
    ServingGeneration,
    ServingGenerationEvent,
    TaxonomyAuthority,
)


class EconomicThemeReadError(ValueError):
    pass


class ServingGenerationUnavailable(EconomicThemeReadError):
    pass


class GenerationNotFound(EconomicThemeReadError):
    pass


class ReaderSnapshotUnavailable(EconomicThemeReadError):
    pass


class ReaderSnapshotCoherenceError(EconomicThemeReadError):
    pass


class EconomicThemeReader:
    """Resolve one serving generation and read only its sealed bundle."""

    def __init__(self, db: Session):
        self.db = db

    def read_catalog(self, generation_id: UUID | None = None) -> dict:
        generation = self.resolve_generation(generation_id)
        return self._read_entry(generation, "economic_themes", "catalog")

    def read_taxonomy_review(self, generation_id: UUID | None = None) -> dict:
        generation = self.resolve_generation(generation_id)
        return self._read_entry(generation, "economic_taxonomy", "review")

    def generation_metadata(self, generation_id: UUID | None = None) -> dict:
        generation = self.resolve_generation(generation_id)
        manifest, bundle = self._load_payload_context(generation)
        return self._metadata(generation, manifest, bundle)

    def resolve_generation(
        self, generation_id: UUID | None = None
    ) -> ServingGeneration:
        if generation_id is None:
            authority = self.db.get(TaxonomyAuthority, 1)
            if authority is None or authority.serving_generation_id is None:
                raise ServingGenerationUnavailable("serving_generation_unavailable")
            generation_id = authority.serving_generation_id
        generation = self.db.get(ServingGeneration, generation_id)
        if generation is None:
            raise GenerationNotFound("generation_not_found")
        return generation

    def _read_entry(self, generation, snapshot_kind, resource_key):
        manifest, bundle = self._load_payload_context(generation)
        entry = self.db.scalar(
            select(ReaderSnapshotEntry).where(
                ReaderSnapshotEntry.reader_snapshot_bundle_id == bundle.id,
                ReaderSnapshotEntry.snapshot_kind == snapshot_kind,
                ReaderSnapshotEntry.resource_key == resource_key,
            )
        )
        if entry is None:
            raise ReaderSnapshotUnavailable("reader_snapshot_entry_unavailable")
        payload = deepcopy(entry.payload)
        if entry.payload_hash != _snapshot_hash(payload):
            raise ReaderSnapshotCoherenceError("reader_snapshot_entry_hash_mismatch")
        indexed_hash = next(
            (
                row.get("payload_hash")
                for row in bundle.payload.get("entries", [])
                if row.get("snapshot_kind") == snapshot_kind
                and row.get("resource_key") == resource_key
            ),
            None,
        )
        if indexed_hash != entry.payload_hash:
            raise ReaderSnapshotCoherenceError("reader_snapshot_index_mismatch")
        expected = {
            "taxonomy_version_id": str(generation.taxonomy_version_id),
            "interpretation_set_id": str(generation.interpretation_set_id),
            "generation_input_manifest_id": str(manifest.id),
            "generation_input_manifest_hash": manifest.semantic_hash,
            "metrics_revision_id": str(generation.metrics_revision_id),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ReaderSnapshotCoherenceError("reader_snapshot_generation_mismatch")
        metadata = self._metadata(generation, manifest, bundle)
        payload.update(
            {
                "generation_id": str(generation.id),
                "generation": metadata,
            }
        )
        return payload

    def _load_payload_context(self, generation):
        manifest = self.db.get(
            GenerationInputManifest, generation.generation_input_manifest_id
        )
        bundle = self.db.get(
            ReaderSnapshotBundle, generation.reader_snapshot_bundle_id
        )
        if (
            manifest is None
            or manifest.status != "sealed"
            or bundle is None
            or bundle.status != "sealed"
        ):
            raise ReaderSnapshotUnavailable("reader_snapshot_unavailable")
        if bundle.generation_input_manifest_id != manifest.id:
            raise ReaderSnapshotCoherenceError("reader_snapshot_manifest_mismatch")
        expected_summary = {
            "taxonomy_version_id": str(generation.taxonomy_version_id),
            "interpretation_set_id": str(generation.interpretation_set_id),
            "generation_input_manifest_id": str(manifest.id),
            "generation_input_manifest_hash": manifest.semantic_hash,
            "metrics_revision_id": str(generation.metrics_revision_id),
        }
        if any(
            bundle.payload.get(key) != value
            for key, value in expected_summary.items()
        ):
            raise ReaderSnapshotCoherenceError("reader_snapshot_generation_mismatch")
        return manifest, bundle

    def _metadata(self, generation, manifest, bundle):
        latest_event = self.db.scalar(
            select(ServingGenerationEvent)
            .where(ServingGenerationEvent.serving_generation_id == generation.id)
            .order_by(ServingGenerationEvent.sequence_number.desc())
            .limit(1)
        )
        return {
            "generation_id": str(generation.id),
            "status": latest_event.event_type if latest_event is not None else "unknown",
            "taxonomy_version_id": str(generation.taxonomy_version_id),
            "interpretation_set_id": str(generation.interpretation_set_id),
            "metrics_revision_id": str(generation.metrics_revision_id),
            "generation_input_manifest_id": str(manifest.id),
            "generation_input_manifest_hash": manifest.semantic_hash,
            "reader_snapshot_bundle_id": str(bundle.id),
            "reader_snapshot_semantic_hash": bundle.semantic_hash,
            "reader_capability_manifest_id": str(
                generation.reader_capability_manifest_id
            ),
            "semantic_hash": generation.semantic_hash,
            "artifact_integrity_hash": generation.artifact_integrity_hash,
        }


def _snapshot_hash(payload) -> str:
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "EconomicThemeReadError",
    "EconomicThemeReader",
    "GenerationNotFound",
    "ReaderSnapshotCoherenceError",
    "ReaderSnapshotUnavailable",
    "ServingGenerationUnavailable",
]
