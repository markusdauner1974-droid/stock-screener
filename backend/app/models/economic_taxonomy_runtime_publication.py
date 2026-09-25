"""Reader, publication, operation, and projection runtime records."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.economic_taxonomy_runtime_common import (
    ImmutableRuntimePayload,
    _created_at,
    _uuid_pk,
)


class ReaderCapabilityManifest(Base):
    __tablename__ = "economic_reader_capability_manifests"

    id = _uuid_pk()
    backend_contract = Column(Integer, nullable=False)
    frontend_contract = Column(Integer, nullable=False)
    migration_version = Column(String(80), nullable=False)
    consumer_test_hash = Column(String(128), nullable=False)
    verified_by = Column(String(200), nullable=False)
    verified_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "backend_contract",
            "frontend_contract",
            "migration_version",
            "consumer_test_hash",
            name="uq_economic_reader_capability_manifest",
        ),
    )


class GenerationInputManifest(Base):
    __tablename__ = "economic_generation_input_manifests"

    id = _uuid_pk()
    status = Column(String(16), nullable=False, default="unsealed")
    expected_parent_generation_id = Column(Uuid(as_uuid=True))
    semantic_invalidation_revision = Column(Integer, nullable=False, default=0)
    committed_revision_tuples = Column(JSON, nullable=False)
    selections = Column(JSON, nullable=False)
    semantic_hash = Column(String(128))
    artifact_integrity_hash = Column(String(128))
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()
    sealed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_economic_generation_input_manifest_status",
        ),
    )

    def seal(self, *, semantic_hash: str, artifact_integrity_hash: str) -> None:
        if self.status != "unsealed":
            raise ImmutableRuntimePayload("sealed_payload_immutable")
        self.status = "sealed"
        self.semantic_hash = semantic_hash
        self.artifact_integrity_hash = artifact_integrity_hash
        self.sealed_at = datetime.now(timezone.utc)


class ReaderSnapshotBundle(Base):
    __tablename__ = "economic_reader_snapshot_bundles"

    id = _uuid_pk()
    status = Column(String(16), nullable=False, default="unsealed")
    generation_input_manifest_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_generation_input_manifests.id"),
        nullable=False,
    )
    payload = Column(JSON, nullable=False)
    semantic_hash = Column(String(128))
    artifact_integrity_hash = Column(String(128))
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()
    sealed_at = Column(DateTime(timezone=True))

    entries = relationship(
        "ReaderSnapshotEntry",
        back_populates="bundle",
        order_by="ReaderSnapshotEntry.snapshot_kind, ReaderSnapshotEntry.resource_key",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_economic_reader_snapshot_bundle_status",
        ),
    )

    def seal(self, *, semantic_hash: str, artifact_integrity_hash: str) -> None:
        if self.status != "unsealed":
            raise ImmutableRuntimePayload("sealed_payload_immutable")
        self.status = "sealed"
        self.semantic_hash = semantic_hash
        self.artifact_integrity_hash = artifact_integrity_hash
        self.sealed_at = datetime.now(timezone.utc)


class ReaderSnapshotEntry(Base):
    __tablename__ = "economic_reader_snapshot_entries"

    id = _uuid_pk()
    reader_snapshot_bundle_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_reader_snapshot_bundles.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_kind = Column(String(80), nullable=False)
    resource_key = Column(String(500), nullable=False)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(128), nullable=False)
    created_at = _created_at()

    bundle = relationship("ReaderSnapshotBundle", back_populates="entries")

    __table_args__ = (
        UniqueConstraint(
            "reader_snapshot_bundle_id",
            "snapshot_kind",
            "resource_key",
            name="uq_economic_reader_snapshot_entry",
        ),
    )


class ReaderSnapshotPointer(Base):
    __tablename__ = "economic_reader_snapshot_pointers"

    reader_key = Column(String(120), primary_key=True)
    serving_generation_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_serving_generations.id")
    )
    reader_snapshot_bundle_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_reader_snapshot_bundles.id"),
    )
    authority_epoch = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(serving_generation_id IS NULL AND reader_snapshot_bundle_id IS NULL) "
            "OR (serving_generation_id IS NOT NULL AND reader_snapshot_bundle_id IS NOT NULL)",
            name="ck_economic_reader_snapshot_pointer_complete",
        ),
    )


class ServingGeneration(Base):
    __tablename__ = "economic_serving_generations"

    id = _uuid_pk()
    expected_parent_generation_id = Column(
        Uuid(as_uuid=True),
        ForeignKey(
            "economic_serving_generations.id",
            use_alter=True,
            name="fk_economic_generation_expected_parent",
        ),
    )
    taxonomy_version_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_versions.id"), nullable=False
    )
    interpretation_set_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_interpretation_sets.id"),
        nullable=False,
    )
    metrics_revision_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_metrics_revisions.id"), nullable=False
    )
    generation_input_manifest_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_generation_input_manifests.id"),
        nullable=False,
    )
    reader_snapshot_bundle_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_reader_snapshot_bundles.id"),
        nullable=False,
    )
    reader_capability_manifest_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_reader_capability_manifests.id"),
        nullable=False,
    )
    semantic_hash = Column(String(128), nullable=False)
    artifact_integrity_hash = Column(String(128), nullable=False)
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()

    events = relationship(
        "ServingGenerationEvent",
        back_populates="serving_generation",
        order_by="ServingGenerationEvent.sequence_number",
    )


class ServingGenerationEvent(Base):
    __tablename__ = "economic_serving_generation_events"

    id = _uuid_pk()
    serving_generation_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_serving_generations.id"),
        nullable=False,
    )
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(24), nullable=False)
    actor = Column(String(200), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    serving_generation = relationship("ServingGeneration", back_populates="events")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('prepared','published','superseded','abandoned')",
            name="ck_economic_serving_generation_event_type",
        ),
        UniqueConstraint(
            "serving_generation_id",
            "sequence_number",
            name="uq_economic_serving_generation_event_sequence",
        ),
    )


class TaxonomyOperationRequest(Base):
    __tablename__ = "economic_taxonomy_operation_requests"

    id = _uuid_pk()
    operation_kind = Column(String(80), nullable=False)
    base_taxonomy_version_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_versions.id"), nullable=False
    )
    request_payload = Column(JSON, nullable=False)
    request_hash = Column(String(128), nullable=False, unique=True)
    actor_subject = Column(String(200), nullable=False)
    auth_method = Column(String(80), nullable=False)
    created_at = _created_at()


class TaxonomyOperationPreview(Base):
    __tablename__ = "economic_taxonomy_operation_previews"

    id = _uuid_pk()
    operation_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_operation_requests.id"),
        nullable=False,
        unique=True,
    )
    candidate_taxonomy_version_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_versions.id"), nullable=False
    )
    preview_hash = Column(String(128), nullable=False, unique=True)
    before_semantic_hash = Column(String(128), nullable=False)
    before_artifact_integrity_hash = Column(String(128), nullable=False)
    after_semantic_hash = Column(String(128), nullable=False)
    after_artifact_integrity_hash = Column(String(128), nullable=False)
    affected_identities = Column(JSON, nullable=False)
    assignments = Column(JSON, nullable=False)
    mappings = Column(JSON, nullable=False)
    compatibility_intents = Column(JSON, nullable=False)
    validation_errors = Column(JSON, nullable=False)
    incompatible_with_prepared_generation = Column(
        Boolean, nullable=False, default=False
    )
    created_at = _created_at()


class TaxonomyOperationEvent(Base):
    __tablename__ = "economic_taxonomy_operation_events"

    id = _uuid_pk()
    operation_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_operation_requests.id"),
        nullable=False,
    )
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(40), nullable=False)
    actor_subject = Column(String(200), nullable=False)
    reason = Column(Text, nullable=False)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('previewed','reviewed','applied','failed')",
            name="ck_economic_taxonomy_operation_event_type",
        ),
        UniqueConstraint(
            "operation_request_id",
            "sequence_number",
            name="uq_economic_taxonomy_operation_event_sequence",
        ),
    )


class TaxonomyProposalEvent(Base):
    __tablename__ = "economic_taxonomy_proposal_events"

    id = _uuid_pk()
    proposal_identity = Column(Uuid(as_uuid=True), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(40), nullable=False)
    actor_subject = Column(String(200), nullable=False)
    reason = Column(Text, nullable=False)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "proposal_identity",
            "sequence_number",
            name="uq_economic_taxonomy_proposal_event_sequence",
        ),
    )


class TaxonomyOverrideEvent(Base):
    __tablename__ = "economic_taxonomy_override_events"

    id = _uuid_pk()
    override_identity = Column(Uuid(as_uuid=True), nullable=False)
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(40), nullable=False)
    actor_subject = Column(String(200), nullable=False)
    reason = Column(Text, nullable=False)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "override_identity",
            "sequence_number",
            name="uq_economic_taxonomy_override_event_sequence",
        ),
    )


class TaxonomyProjectionEvent(Base):
    __tablename__ = "economic_taxonomy_projection_events"

    id = _uuid_pk()
    serving_generation_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_serving_generations.id")
    )
    source_lineage = Column(String(500), nullable=False)
    projection_revision = Column(Integer, nullable=False)
    projection_kind = Column(String(80), nullable=False)
    projection_version = Column(Integer, nullable=False)
    target_representation = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(128), nullable=False)
    origin_representation = Column(String(80), nullable=False)
    delivery_scope = Column(String(24), nullable=False, default="candidate")
    staged_epoch = Column(Integer, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        CheckConstraint(
            "projection_revision > 0 AND projection_version > 0",
            name="ck_economic_projection_positive_revisions",
        ),
        CheckConstraint(
            "delivery_scope IN ('shadow','candidate')",
            name="ck_economic_projection_delivery_scope",
        ),
        UniqueConstraint(
            "source_lineage",
            "projection_revision",
            "projection_kind",
            "projection_version",
            "target_representation",
            name="uq_economic_projection_logical_event",
        ),
        Index(
            "ix_economic_projection_generation_scope",
            "serving_generation_id",
            "delivery_scope",
        ),
    )


class TaxonomyProjectionDeliveryAttempt(Base):
    __tablename__ = "economic_taxonomy_projection_delivery_attempts"

    id = _uuid_pk()
    projection_event_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_projection_events.id"),
        nullable=False,
    )
    attempt_number = Column(Integer, nullable=False)
    claimed_epoch = Column(Integer, nullable=False)
    lease_token = Column(Uuid(as_uuid=True), nullable=False, unique=True)
    lease_owner = Column(String(200), nullable=False)
    lease_expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "projection_event_id",
            "attempt_number",
            name="uq_economic_projection_delivery_attempt_number",
        ),
    )


class TaxonomyProjectionDeliveryEvent(Base):
    __tablename__ = "economic_taxonomy_projection_delivery_events"

    id = _uuid_pk()
    delivery_attempt_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_projection_delivery_attempts.id"),
        nullable=False,
        unique=True,
    )
    outcome = Column(String(40), nullable=False)
    error = Column(Text)
    details = Column(JSON, nullable=False, default=dict)
    completed_at = _created_at()

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success','stale_noop','retryable_failure','terminal_failure')",
            name="ck_economic_projection_delivery_outcome",
        ),
    )


class ProjectionCheckpoint(Base):
    __tablename__ = "economic_taxonomy_projection_checkpoints"

    target_representation = Column(String(80), primary_key=True)
    source_lineage = Column(String(500), primary_key=True)
    projection_kind = Column(String(80), primary_key=True)
    last_applied_revision = Column(Integer, nullable=False)
    projection_event_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_projection_events.id")
    )
    origin_representation = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TaxonomyAuthority(Base):
    __tablename__ = "taxonomy_authority"

    id = Column(Integer, primary_key=True, default=1)
    mode = Column(String(16), nullable=False, default="legacy")
    processing_taxonomy_version_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_versions.id")
    )
    processing_head_revision = Column(Integer, nullable=False, default=0)
    serving_generation_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_serving_generations.id")
    )
    authority_epoch = Column(Integer, nullable=False, default=1)
    writes_fenced = Column(Boolean, nullable=False, default=False)
    semantic_invalidation_revision = Column(Integer, nullable=False, default=0)
    cutover_catch_up_cursor = Column(JSON, nullable=False, default=list)
    rollback_state = Column(String(40), nullable=False, default="ready")
    rollback_reason = Column(Text)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_taxonomy_authority_singleton"),
        CheckConstraint(
            "mode IN ('legacy','shadow','dual','economic')",
            name="ck_taxonomy_authority_mode",
        ),
    )


__all__ = (
    "GenerationInputManifest",
    "ProjectionCheckpoint",
    "ReaderCapabilityManifest",
    "ReaderSnapshotBundle",
    "ReaderSnapshotEntry",
    "ReaderSnapshotPointer",
    "ServingGeneration",
    "ServingGenerationEvent",
    "TaxonomyAuthority",
    "TaxonomyOperationEvent",
    "TaxonomyOperationPreview",
    "TaxonomyOperationRequest",
    "TaxonomyOverrideEvent",
    "TaxonomyProjectionDeliveryAttempt",
    "TaxonomyProjectionDeliveryEvent",
    "TaxonomyProjectionEvent",
    "TaxonomyProposalEvent",
)
