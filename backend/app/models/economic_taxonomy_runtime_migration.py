"""Migration and benchmark runtime records."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)

from app.database import Base
from app.models.economic_taxonomy_runtime_common import (
    ImmutableRuntimePayload,
    _created_at,
    _uuid_pk,
)


class TaxonomyMigrationRun(Base):
    __tablename__ = "taxonomy_migration_runs"

    id = _uuid_pk()
    taxonomy_version_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(String(16), nullable=False, default="unsealed")
    dataset_manifest = Column(JSON, nullable=False)
    source_hashes = Column(JSON, nullable=False)
    taxonomy_semantic_hash = Column(String(128), nullable=False)
    taxonomy_artifact_integrity_hash = Column(String(128), nullable=False)
    policy_bundle = Column(JSON, nullable=False)
    policy_bundle_hash = Column(String(128), nullable=False)
    migration_policy_version = Column(String(120), nullable=False)
    input_semantic_hash = Column(String(128), nullable=False, unique=True)
    artifact_integrity_hash = Column(String(128))
    identity_count = Column(Integer, nullable=False)
    reviewed_identity_count_cache = Column(Integer, nullable=False, default=0)
    coverage_complete_cache = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()
    sealed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_taxonomy_migration_run_status",
        ),
    )

    @property
    def coverage_complete(self) -> bool:
        return bool(self.coverage_complete_cache)

    def seal(self, *, artifact_integrity_hash: str) -> None:
        if self.status != "unsealed":
            raise ImmutableRuntimePayload("migration_run_inputs_immutable")
        self.status = "sealed"
        self.artifact_integrity_hash = artifact_integrity_hash
        self.sealed_at = datetime.now(timezone.utc)


class TaxonomyMigrationReview(Base):
    __tablename__ = "taxonomy_migration_reviews"

    id = _uuid_pk()
    migration_run_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("taxonomy_migration_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    legacy_theme_cluster_id = Column(Integer, nullable=False)
    review_revision = Column(Integer, nullable=False)
    disposition = Column(String(40), nullable=False)
    destination_theme_ids = Column(JSON, nullable=False)
    allocations = Column(JSON, nullable=False)
    reviewer_subject = Column(String(200), nullable=False)
    reviewer_auth_method = Column(String(120), nullable=False)
    reason = Column(Text, nullable=False)
    semantic_hash = Column(String(128), nullable=False)
    created_at = _created_at()

    __table_args__ = (
        CheckConstraint(
            "disposition IN ('mapped','split_required','merged_equivalent',"
            "'not_a_theme','deferred')",
            name="ck_taxonomy_migration_review_disposition",
        ),
        UniqueConstraint(
            "migration_run_id",
            "legacy_theme_cluster_id",
            "review_revision",
            name="uq_taxonomy_migration_review_revision",
        ),
    )


class TaxonomyMigrationProgressEvent(Base):
    __tablename__ = "taxonomy_migration_progress_events"

    id = _uuid_pk()
    migration_run_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("taxonomy_migration_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(24), nullable=False)
    actor_subject = Column(String(200), nullable=False)
    actor_auth_method = Column(String(120), nullable=False)
    reason = Column(Text, nullable=False)
    event_payload = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('started','progress','paused','failed','reviewed',"
            "'replayed','completed')",
            name="ck_taxonomy_migration_progress_event_type",
        ),
        UniqueConstraint(
            "migration_run_id",
            "sequence_number",
            name="uq_taxonomy_migration_progress_event_sequence",
        ),
    )


class SemanticInvalidationRevision(Base):
    __tablename__ = "economic_semantic_invalidation_revisions"

    id = _uuid_pk()
    revision_number = Column(Integer, nullable=False, unique=True)
    reason = Column(Text, nullable=False)
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()


class TaxonomyBenchmarkResult(Base):
    __tablename__ = "economic_taxonomy_benchmark_results"

    id = _uuid_pk()
    taxonomy_semantic_hash = Column(String(128), nullable=False)
    policy_bundle = Column(String(160), nullable=False)
    fixture_version = Column(Integer, nullable=False)
    report = Column(JSON, nullable=False)
    report_hash = Column(String(128), nullable=False)
    passed = Column(Boolean, nullable=False)
    verified_by = Column(String(200), nullable=False)
    created_at = _created_at()

    __table_args__ = (
        CheckConstraint("passed", name="ck_economic_taxonomy_benchmark_passed"),
        UniqueConstraint(
            "taxonomy_semantic_hash",
            "policy_bundle",
            "report_hash",
            name="uq_economic_taxonomy_benchmark_result",
        ),
    )


__all__ = (
    "SemanticInvalidationRevision",
    "TaxonomyBenchmarkResult",
    "TaxonomyMigrationProgressEvent",
    "TaxonomyMigrationReview",
    "TaxonomyMigrationRun",
)
