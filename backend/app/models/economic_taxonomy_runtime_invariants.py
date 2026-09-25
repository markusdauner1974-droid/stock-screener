"""Runtime immutability rules and database trigger registration."""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import DDL, event, func, inspect, select
from sqlalchemy.orm import Session

from app.models.economic_taxonomy import TaxonomyVersion
from app.models.economic_taxonomy_runtime_common import ImmutableRuntimePayload
from app.models.economic_taxonomy_runtime_evidence import *
from app.models.economic_taxonomy_runtime_migration import *
from app.models.economic_taxonomy_runtime_publication import *

APPEND_ONLY_RUNTIME_MODELS = (
    SourceFamily,
    SourceLineage,
    EvidencePacket,
    EvidencePrecedenceRevision,
    LensEligibilityRevision,
    ProcessingRequestEvent,
    ProviderAttempt,
    ProviderAttemptEvent,
    EconomicExposureCandidate,
    DimensionProposal,
    NamingProposal,
    ExtractionArtifact,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    ClaimAssignment,
    InterpretationOverrideRevision,
    SocialAssociationRevisionRef,
    ConstituentDecisionRevision,
    ProposalDecisionRevision,
    DevelopmentSelectionRevision,
    InterpretationSelection,
    ThemeObservation,
    ThemeConstituentExposure,
    ThemeSignalObservation,
    EconomicThemeEmbedding,
    ThemeMetric,
    TaxonomySourceRevisionLog,
    TaxonomyMigrationReview,
    TaxonomyMigrationProgressEvent,
    SemanticInvalidationRevision,
    TaxonomyBenchmarkResult,
    ReaderCapabilityManifest,
    ServingGeneration,
    ServingGenerationEvent,
    TaxonomyOperationRequest,
    TaxonomyOperationPreview,
    TaxonomyOperationEvent,
    TaxonomyProposalEvent,
    TaxonomyOverrideEvent,
    TaxonomyProjectionEvent,
    TaxonomyProjectionDeliveryAttempt,
    TaxonomyProjectionDeliveryEvent,
)

SEALED_RUNTIME_MODELS = (
    InterpretationSet,
    MetricsRevision,
    GenerationInputManifest,
    ReaderSnapshotBundle,
)

ECONOMIC_TAXONOMY_RUNTIME_TABLES = [
    SourceFamily.__table__,
    SourceLineage.__table__,
    EvidencePacket.__table__,
    EvidencePrecedenceRevision.__table__,
    LensEligibilityRevision.__table__,
    ProcessingRequest.__table__,
    ProcessingRequestEvent.__table__,
    ProviderAttempt.__table__,
    ProviderAttemptEvent.__table__,
    EconomicExposureCandidate.__table__,
    DimensionProposal.__table__,
    NamingProposal.__table__,
    ExtractionArtifact.__table__,
    ClaimReviewArtifact.__table__,
    ClassificationAttempt.__table__,
    ClassificationAttemptEvent.__table__,
    ClaimAssignment.__table__,
    InterpretationOverrideRevision.__table__,
    SocialAssociationRevisionRef.__table__,
    ConstituentDecisionRevision.__table__,
    ProposalDecisionRevision.__table__,
    DevelopmentSelectionRevision.__table__,
    InterpretationSet.__table__,
    InterpretationSelection.__table__,
    ThemeObservation.__table__,
    ThemeConstituentExposure.__table__,
    ThemeSignalObservation.__table__,
    EconomicThemeEmbedding.__table__,
    MetricsRevision.__table__,
    ThemeMetric.__table__,
    TaxonomySourceRevisionLog.__table__,
    TaxonomyMigrationRun.__table__,
    TaxonomyMigrationReview.__table__,
    TaxonomyMigrationProgressEvent.__table__,
    SemanticInvalidationRevision.__table__,
    TaxonomyBenchmarkResult.__table__,
    ReaderCapabilityManifest.__table__,
    GenerationInputManifest.__table__,
    ReaderSnapshotBundle.__table__,
    ReaderSnapshotEntry.__table__,
    ReaderSnapshotPointer.__table__,
    ServingGeneration.__table__,
    ServingGenerationEvent.__table__,
    TaxonomyOperationRequest.__table__,
    TaxonomyOperationPreview.__table__,
    TaxonomyOperationEvent.__table__,
    TaxonomyProposalEvent.__table__,
    TaxonomyOverrideEvent.__table__,
    TaxonomyProjectionEvent.__table__,
    TaxonomyProjectionDeliveryAttempt.__table__,
    TaxonomyProjectionDeliveryEvent.__table__,
    ProjectionCheckpoint.__table__,
    TaxonomyAuthority.__table__,
]


def _allocate_evidence_ordinals(session: Session) -> None:
    pending = defaultdict(list)
    for row in session.new:
        if isinstance(row, EvidencePacket) and row.evidence_revision_ordinal is None:
            pending[row.source_lineage_id].append(row)

    for lineage_id, rows in pending.items():
        if lineage_id is None:
            raise ImmutableRuntimePayload("evidence_lineage_must_be_persisted")
        with session.no_autoflush:
            # PostgreSQL serializes all ordinal allocators for this lineage.  On
            # SQLite the query remains harmless and the uniqueness constraint is
            # the final guard.
            session.execute(
                select(SourceLineage.id)
                .where(SourceLineage.id == lineage_id)
                .with_for_update()
            ).scalar_one()
            current = session.execute(
                select(func.max(EvidencePacket.evidence_revision_ordinal)).where(
                    EvidencePacket.source_lineage_id == lineage_id
                )
            ).scalar_one()
        ordinal = int(current or 0)
        for row in rows:
            ordinal += 1
            row.evidence_revision_ordinal = ordinal


def _protect_sealable(row) -> None:
    state = inspect(row)
    prior = state.attrs.status.history.deleted
    prior_status = prior[0] if prior else row.status
    if prior_status == "sealed":
        raise ImmutableRuntimePayload("sealed_payload_immutable")

    if row.status == "unsealed":
        return

    changed = {
        attr.key
        for attr in state.mapper.column_attrs
        if state.attrs[attr.key].history.has_changes()
    }
    permitted = {"status", "semantic_hash", "artifact_integrity_hash", "sealed_at"}
    if row.status != "sealed" or not changed.issubset(permitted):
        raise ImmutableRuntimePayload("runtime_payload_immutable")
    if (
        not row.semantic_hash
        or not row.artifact_integrity_hash
        or row.sealed_at is None
    ):
        raise ImmutableRuntimePayload("sealed_payload_incomplete")


def _normalize_generation_manifest(row: GenerationInputManifest) -> None:
    row.committed_revision_tuples = sorted(
        row.committed_revision_tuples or [],
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )
    row.selections = sorted(
        row.selections or [],
        key=lambda item: (
            str(item.get("lineage", "")),
            str(item.get("evidence_packet_id", "")),
            json.dumps(item, sort_keys=True, separators=(",", ":")),
        ),
    )


def _validate_serving_generation(session: Session, row: ServingGeneration) -> None:
    with session.no_autoflush:
        taxonomy = session.get(TaxonomyVersion, row.taxonomy_version_id)
        interpretation = session.get(InterpretationSet, row.interpretation_set_id)
        metrics = session.get(MetricsRevision, row.metrics_revision_id)
        manifest = session.get(
            GenerationInputManifest, row.generation_input_manifest_id
        )
        snapshots = session.get(ReaderSnapshotBundle, row.reader_snapshot_bundle_id)
        capability = session.get(
            ReaderCapabilityManifest, row.reader_capability_manifest_id
        )
    if any(
        value is None
        for value in (
            taxonomy,
            interpretation,
            metrics,
            manifest,
            snapshots,
            capability,
        )
    ):
        raise ImmutableRuntimePayload("generation_reference_missing")
    if taxonomy.status != "sealed" or any(
        value.status != "sealed"
        for value in (interpretation, metrics, manifest, snapshots)
    ):
        raise ImmutableRuntimePayload("generation_payload_unsealed")
    if {
        interpretation.generation_input_manifest_id,
        metrics.generation_input_manifest_id,
        snapshots.generation_input_manifest_id,
    } != {manifest.id}:
        raise ImmutableRuntimePayload("manifest_mismatch")


@event.listens_for(Session, "before_flush")
def _protect_economic_taxonomy_runtime(session, _flush_context, _instances):
    _allocate_evidence_ordinals(session)

    for row in session.new:
        if isinstance(row, GenerationInputManifest):
            _normalize_generation_manifest(row)
        elif isinstance(row, ServingGeneration):
            _validate_serving_generation(session, row)

    for row in session.deleted:
        if isinstance(row, TaxonomyMigrationRun):
            raise ImmutableRuntimePayload("migration_run_inputs_immutable")
        if isinstance(row, ReaderSnapshotEntry):
            with session.no_autoflush:
                parent = session.get(
                    ReaderSnapshotBundle, row.reader_snapshot_bundle_id
                )
            if parent is not None and parent.status == "sealed":
                raise ImmutableRuntimePayload("sealed_payload_immutable")
        if isinstance(row, APPEND_ONLY_RUNTIME_MODELS + SEALED_RUNTIME_MODELS):
            raise ImmutableRuntimePayload("runtime_payload_immutable")

    for row in session.dirty:
        if isinstance(row, TaxonomyMigrationRun):
            state = inspect(row)
            immutable_fields = (
                "taxonomy_version_id",
                "status",
                "dataset_manifest",
                "source_hashes",
                "taxonomy_semantic_hash",
                "taxonomy_artifact_integrity_hash",
                "policy_bundle",
                "policy_bundle_hash",
                "migration_policy_version",
                "input_semantic_hash",
                "artifact_integrity_hash",
                "identity_count",
                "created_by",
                "sealed_at",
            )
            prior_statuses = state.attrs.status.history.deleted
            prior_status = prior_statuses[0] if prior_statuses else row.status
            changed = {
                name
                for name in immutable_fields
                if state.attrs[name].history.has_changes()
            }
            allowed_seal = (
                prior_status == "unsealed"
                and row.status == "sealed"
                and changed.issubset({"status", "artifact_integrity_hash", "sealed_at"})
            )
            if changed and not allowed_seal:
                raise ImmutableRuntimePayload("migration_run_inputs_immutable")
        if isinstance(row, ReaderSnapshotEntry):
            with session.no_autoflush:
                parent = session.get(
                    ReaderSnapshotBundle, row.reader_snapshot_bundle_id
                )
            if parent is not None and parent.status == "sealed":
                raise ImmutableRuntimePayload("sealed_payload_immutable")
        if isinstance(row, APPEND_ONLY_RUNTIME_MODELS):
            raise ImmutableRuntimePayload("runtime_payload_immutable")
        if isinstance(row, SEALED_RUNTIME_MODELS):
            _protect_sealable(row)

    for row in session.new:
        parent_type = None
        parent_id = None
        if isinstance(row, InterpretationSelection):
            parent_type = InterpretationSet
            parent_id = row.interpretation_set_id
        elif isinstance(row, ThemeMetric):
            parent_type = MetricsRevision
            parent_id = row.metrics_revision_id
        elif isinstance(row, ReaderSnapshotEntry):
            parent_type = ReaderSnapshotBundle
            parent_id = row.reader_snapshot_bundle_id
        if parent_type is None or parent_id is None:
            continue
        with session.no_autoflush:
            parent = session.get(parent_type, parent_id)
        if parent is not None and parent.status == "sealed":
            raise ImmutableRuntimePayload("sealed_payload_immutable")


_CREATE_RUNTIME_TRIGGER_FUNCTIONS = DDL(
    """
    CREATE OR REPLACE FUNCTION economic_runtime_reject_mutation()
    RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'runtime_payload_immutable';
    END;
    $$ LANGUAGE plpgsql;

    CREATE OR REPLACE FUNCTION economic_runtime_seal_once()
    RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' OR OLD.status = 'sealed' THEN
        RAISE EXCEPTION 'sealed_payload_immutable';
      END IF;
      IF NEW.status <> 'sealed'
         OR NEW.semantic_hash IS NULL
         OR NEW.artifact_integrity_hash IS NULL
         OR NEW.sealed_at IS NULL
         OR (to_jsonb(NEW) - ARRAY['status','semantic_hash','artifact_integrity_hash','sealed_at']::text[])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['status','semantic_hash','artifact_integrity_hash','sealed_at']::text[]) THEN
        RAISE EXCEPTION 'runtime_payload_immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE OR REPLACE FUNCTION economic_runtime_guard_interpretation_child()
    RETURNS trigger AS $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM economic_interpretation_sets
        WHERE id = NEW.interpretation_set_id AND status = 'sealed'
        FOR KEY SHARE
      ) THEN
        RAISE EXCEPTION 'sealed_payload_immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE OR REPLACE FUNCTION economic_runtime_guard_metric_child()
    RETURNS trigger AS $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM economic_metrics_revisions
        WHERE id = NEW.metrics_revision_id AND status = 'sealed'
        FOR KEY SHARE
      ) THEN
        RAISE EXCEPTION 'sealed_payload_immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE OR REPLACE FUNCTION economic_runtime_guard_snapshot_child()
    RETURNS trigger AS $$
    DECLARE
      bundle_id uuid;
    BEGIN
      bundle_id := CASE WHEN TG_OP = 'DELETE'
                        THEN OLD.reader_snapshot_bundle_id
                        ELSE NEW.reader_snapshot_bundle_id END;
      IF EXISTS (
        SELECT 1 FROM economic_reader_snapshot_bundles
        WHERE id = bundle_id AND status = 'sealed'
        FOR KEY SHARE
      ) THEN
        RAISE EXCEPTION 'sealed_payload_immutable';
      END IF;
      RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")

event.listen(SourceFamily.__table__, "after_create", _CREATE_RUNTIME_TRIGGER_FUNCTIONS)

event.listen(
    TaxonomyMigrationRun.__table__,
    "after_create",
    DDL(
        """
        CREATE OR REPLACE FUNCTION economic_migration_run_guard()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'migration_run_inputs_immutable';
          END IF;
          IF OLD.status = 'sealed' THEN
            IF (to_jsonb(NEW) - ARRAY['reviewed_identity_count_cache','coverage_complete_cache']::text[])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['reviewed_identity_count_cache','coverage_complete_cache']::text[]) THEN
              RAISE EXCEPTION 'migration_run_inputs_immutable';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.status <> 'sealed'
             OR NEW.artifact_integrity_hash IS NULL
             OR NEW.sealed_at IS NULL
             OR (to_jsonb(NEW) - ARRAY['status','artifact_integrity_hash','sealed_at']::text[])
                IS DISTINCT FROM
                (to_jsonb(OLD) - ARRAY['status','artifact_integrity_hash','sealed_at']::text[]) THEN
            RAISE EXCEPTION 'migration_run_inputs_immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_taxonomy_migration_run_guard
        BEFORE UPDATE OR DELETE ON taxonomy_migration_runs
        FOR EACH ROW EXECUTE FUNCTION economic_migration_run_guard();
        """
    ).execute_if(dialect="postgresql"),
)

for _runtime_model in APPEND_ONLY_RUNTIME_MODELS:
    event.listen(
        _runtime_model.__table__,
        "after_create",
        DDL(
            f"""
            CREATE TRIGGER trg_{_runtime_model.__tablename__}_append_only
            BEFORE UPDATE OR DELETE ON {_runtime_model.__tablename__}
            FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation();
            """
        ).execute_if(dialect="postgresql"),
    )

for _sealed_model in SEALED_RUNTIME_MODELS:
    event.listen(
        _sealed_model.__table__,
        "after_create",
        DDL(
            f"""
            CREATE TRIGGER trg_{_sealed_model.__tablename__}_seal_once
            BEFORE UPDATE OR DELETE ON {_sealed_model.__tablename__}
            FOR EACH ROW EXECUTE FUNCTION economic_runtime_seal_once();
            """
        ).execute_if(dialect="postgresql"),
    )

event.listen(
    InterpretationSelection.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_economic_interpretation_selection_parent_open
        BEFORE INSERT ON economic_interpretation_selections
        FOR EACH ROW EXECUTE FUNCTION economic_runtime_guard_interpretation_child();
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    ThemeMetric.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_economic_theme_metric_parent_open
        BEFORE INSERT ON economic_theme_metrics
        FOR EACH ROW EXECUTE FUNCTION economic_runtime_guard_metric_child();
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    ReaderSnapshotEntry.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_economic_reader_snapshot_entry_parent_open
        BEFORE INSERT OR UPDATE OR DELETE ON economic_reader_snapshot_entries
        FOR EACH ROW EXECUTE FUNCTION economic_runtime_guard_snapshot_child();
        """
    ).execute_if(dialect="postgresql"),
)
