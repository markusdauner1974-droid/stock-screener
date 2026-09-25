"""Stable contracts and errors for Economic Taxonomy publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.economic_taxonomy_runtime import ServingGeneration


class PublicationError(RuntimeError):
    """Base error for a publication that did not switch authority."""


class PublicationForbidden(PermissionError):
    pass


class ManifestChanged(PublicationError):
    pass


class CompatibilityNotAcknowledged(PublicationError):
    pass


class ReaderCapabilityRejected(PublicationError):
    pass


class BenchmarkRejected(PublicationError):
    pass


class InjectedPublicationCrash(RuntimeError):
    """Fault used by recovery tests after a durable commit."""


@dataclass(frozen=True, slots=True)
class PublicationCutoff:
    manifest_id: UUID
    manifest_semantic_hash: str
    processing_taxonomy_version_id: UUID
    processing_head_revision: int
    expected_parent_generation_id: UUID | None
    semantic_invalidation_revision: int
    authority_epoch: int
    committed_revision_tuples: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class PreparationContext:
    manifest_id: UUID
    taxonomy_version_id: UUID
    interpretation_set_id: UUID
    metrics_revision_id: UUID
    reader_snapshot_bundle_id: UUID
    expected_parent_generation_id: UUID | None
    staged_epoch: int
    target_mode: str


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    id: UUID
    manifest_id: UUID
    taxonomy_version_id: UUID
    interpretation_set_id: UUID
    metrics_revision_id: UUID
    reader_snapshot_bundle_id: UUID
    target_mode: str

    def load(self, session: Session) -> ServingGeneration:
        row = session.get(ServingGeneration, self.id)
        if row is None:
            raise KeyError(f"serving generation {self.id} not found")
        return row


@dataclass(frozen=True, slots=True)
class PublishedGeneration:
    id: UUID
    authority_epoch: int
    mode: str
    rollback_state: str
