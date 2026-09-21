"""Immutable runtime evidence, interpretation, and metrics persistence.

The semantic taxonomy is versioned separately in :mod:`economic_taxonomy`.
This module records the evidence and processing history used to interpret that
taxonomy.  Rows are append-only; the two aggregate payloads are built while
unsealed and allow one audited transition to ``sealed``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    DDL,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import Session, relationship

from app.database import Base


class ImmutableRuntimePayload(ValueError):
    """Raised when an append-only runtime fact would be changed."""


def _uuid_pk():
    return Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def _created_at():
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SourceFamily(Base):
    __tablename__ = "economic_source_families"

    id = _uuid_pk()
    provider = Column(String(80), nullable=False)
    canonical_source_key = Column(String(500), nullable=False, unique=True)
    canonical_item_id = Column(String(240))
    created_at = _created_at()


class SourceLineage(Base):
    __tablename__ = "economic_source_lineages"

    id = _uuid_pk()
    source_family_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_source_families.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scope_suffix = Column(String(240), nullable=False, default="")
    admission_policy_key = Column(String(120))
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "source_family_id", "scope_suffix", name="uq_economic_source_lineage_scope"
        ),
        CheckConstraint(
            "scope_suffix = '' OR admission_policy_key IS NOT NULL",
            name="ck_economic_source_lineage_scoped_policy",
        ),
    )


class EvidencePacket(Base):
    __tablename__ = "economic_evidence_packets"

    id = _uuid_pk()
    source_lineage_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_source_lineages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence_revision_ordinal = Column(Integer, nullable=False)
    packet_hash = Column(String(128), nullable=False)
    evidence_content_fingerprint = Column(String(128), nullable=False)
    provider_revision_id = Column(String(240))
    provider_revision_order = Column(String(240))
    capture_route = Column(String(80), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    supersedes_evidence_packet_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_evidence_packets.id", ondelete="RESTRICT"),
    )
    equivalent_evidence_packet_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_evidence_packets.id", ondelete="RESTRICT"),
    )
    precedence_state = Column(String(32), nullable=False)
    original_text_ref = Column(Text, nullable=False)
    translated_text_ref = Column(Text)
    translation_version = Column(String(120))
    attachment_hashes = Column(JSON, nullable=False)
    extracted_text_hashes = Column(JSON, nullable=False)
    grounding_snapshot = Column(JSON, nullable=False)
    preparation_version = Column(String(120), nullable=False)
    source_metadata = Column(JSON, nullable=False)
    observed_at = Column(DateTime(timezone=True))
    available_at = Column(DateTime(timezone=True), nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "source_lineage_id",
            "evidence_revision_ordinal",
            name="uq_economic_evidence_lineage_ordinal",
        ),
        UniqueConstraint(
            "source_lineage_id", "packet_hash", name="uq_economic_evidence_packet_hash"
        ),
        CheckConstraint(
            "precedence_state IN ('effective','superseded','equivalent','hold_review')",
            name="ck_economic_evidence_precedence_state",
        ),
    )


class EvidencePrecedenceRevision(Base):
    __tablename__ = "economic_evidence_precedence_revisions"

    id = _uuid_pk()
    source_lineage_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_source_lineages.id"), nullable=False
    )
    evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id"), nullable=False
    )
    revision_number = Column(Integer, nullable=False)
    disposition = Column(String(32), nullable=False)
    related_evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id")
    )
    reason = Column(Text, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "revision_number",
            name="uq_economic_evidence_precedence_revision",
        ),
    )


class LensEligibilityRevision(Base):
    __tablename__ = "economic_lens_eligibility_revisions"

    id = _uuid_pk()
    source_lineage_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_source_lineages.id"), nullable=False
    )
    evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id"), nullable=False
    )
    revision_number = Column(Integer, nullable=False)
    evidence_channels = Column(JSON, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "revision_number",
            name="uq_economic_lens_eligibility_revision",
        ),
    )


class ProcessingRequest(Base):
    __tablename__ = "economic_processing_requests"

    id = _uuid_pk()
    source_lineage_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_source_lineages.id"), nullable=False
    )
    evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id"), nullable=False
    )
    policy_bundle_version = Column(String(160), nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "policy_bundle_version",
            name="uq_economic_processing_request_identity",
        ),
    )


class ExtractionArtifact(Base):
    __tablename__ = "economic_extraction_artifacts"

    id = _uuid_pk()
    evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id"), nullable=False
    )
    extraction_policy_version = Column(String(120), nullable=False)
    result_status = Column(String(40), nullable=False)
    result_payload = Column(JSON, nullable=False)
    provider_response_hash = Column(String(128))
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "evidence_packet_id",
            "extraction_policy_version",
            name="uq_economic_extraction_artifact_key",
        ),
    )


class ClaimReviewArtifact(Base):
    __tablename__ = "economic_claim_review_artifacts"

    id = _uuid_pk()
    extraction_artifact_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_extraction_artifacts.id"), nullable=False
    )
    claim_review_policy_version = Column(String(120), nullable=False)
    facet_catalog_semantic_hash = Column(String(128), nullable=False)
    result_status = Column(String(40), nullable=False)
    result_payload = Column(JSON, nullable=False)
    provider_response_hash = Column(String(128))
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "extraction_artifact_id",
            "claim_review_policy_version",
            "facet_catalog_semantic_hash",
            name="uq_economic_claim_review_artifact_key",
        ),
    )


class ClassificationAttempt(Base):
    __tablename__ = "economic_classification_attempts"

    id = _uuid_pk()
    processing_request_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_processing_requests.id"), nullable=False
    )
    claim_review_artifact_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_claim_review_artifacts.id"), nullable=False
    )
    input_taxonomy_version_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_versions.id"), nullable=False
    )
    output_taxonomy_version_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_taxonomy_versions.id")
    )
    resolver_policy_version = Column(String(120), nullable=False)
    naming_policy_version = Column(String(120), nullable=False)
    derivation_policy_version = Column(String(120), nullable=False)
    result_status = Column(String(40), nullable=False)
    result_payload = Column(JSON, nullable=False)
    created_at = _created_at()

    assignments = relationship(
        "ClaimAssignment",
        back_populates="classification_attempt",
        order_by="ClaimAssignment.created_at",
    )

    __table_args__ = (
        UniqueConstraint(
            "processing_request_id",
            "claim_review_artifact_id",
            "input_taxonomy_version_id",
            "resolver_policy_version",
            "naming_policy_version",
            "derivation_policy_version",
            name="uq_economic_classification_attempt_key",
        ),
    )


class ClassificationAttemptEvent(Base):
    __tablename__ = "economic_classification_attempt_events"

    id = _uuid_pk()
    classification_attempt_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_classification_attempts.id"), nullable=False
    )
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(40), nullable=False)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "classification_attempt_id",
            "sequence_number",
            name="uq_economic_classification_attempt_event_sequence",
        ),
    )


class ClaimAssignment(Base):
    __tablename__ = "economic_claim_assignments"

    id = _uuid_pk()
    classification_attempt_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_classification_attempts.id"), nullable=False
    )
    claim_fingerprint = Column(String(128), nullable=False)
    economic_theme_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_themes.id"), nullable=False
    )
    exposure_support = Column(String(40), nullable=False)
    claim_payload = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=False)
    created_at = _created_at()

    classification_attempt = relationship(
        "ClassificationAttempt", back_populates="assignments"
    )

    __table_args__ = (
        UniqueConstraint(
            "classification_attempt_id",
            "claim_fingerprint",
            "economic_theme_id",
            name="uq_economic_claim_assignment_identity",
        ),
    )


class InterpretationOverrideRevision(Base):
    __tablename__ = "economic_interpretation_override_revisions"

    id = _uuid_pk()
    source_lineage_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_source_lineages.id"), nullable=False
    )
    revision_number = Column(Integer, nullable=False)
    override_kind = Column(String(60), nullable=False)
    payload = Column(JSON, nullable=False)
    reason = Column(Text, nullable=False)
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "source_lineage_id",
            "revision_number",
            name="uq_economic_interpretation_override_revision",
        ),
    )


class SocialAssociationRevisionRef(Base):
    __tablename__ = "economic_social_association_revision_refs"

    id = _uuid_pk()
    association_id = Column(Uuid(as_uuid=True), nullable=False)
    revision_number = Column(Integer, nullable=False)
    decision_revision_id = Column(Uuid(as_uuid=True))
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "association_id",
            "revision_number",
            name="uq_economic_social_association_revision_ref",
        ),
    )


class ConstituentDecisionRevision(Base):
    __tablename__ = "economic_constituent_decision_revisions"

    id = _uuid_pk()
    association_revision_ref_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_social_association_revision_refs.id"),
        nullable=False,
    )
    revision_number = Column(Integer, nullable=False)
    decision = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "association_revision_ref_id",
            "revision_number",
            name="uq_economic_constituent_decision_revision",
        ),
    )


class ProposalDecisionRevision(Base):
    __tablename__ = "economic_proposal_decision_revisions"

    id = _uuid_pk()
    proposal_identity = Column(Uuid(as_uuid=True), nullable=False)
    revision_number = Column(Integer, nullable=False)
    decision = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "proposal_identity",
            "revision_number",
            name="uq_economic_proposal_decision_revision",
        ),
    )


class DevelopmentSelectionRevision(Base):
    __tablename__ = "economic_development_selection_revisions"

    id = _uuid_pk()
    development_identity = Column(Uuid(as_uuid=True), nullable=False)
    revision_number = Column(Integer, nullable=False)
    selected = Column(Boolean, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "development_identity",
            "revision_number",
            name="uq_economic_development_selection_revision",
        ),
    )


class InterpretationSet(Base):
    __tablename__ = "economic_interpretation_sets"

    id = _uuid_pk()
    status = Column(String(16), nullable=False, default="unsealed")
    semantic_hash = Column(String(128))
    artifact_integrity_hash = Column(String(128))
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()
    sealed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_economic_interpretation_set_status",
        ),
    )

    def seal(self, *, semantic_hash: str, artifact_integrity_hash: str) -> None:
        if self.status != "unsealed":
            raise ImmutableRuntimePayload("sealed_payload_immutable")
        self.status = "sealed"
        self.semantic_hash = semantic_hash
        self.artifact_integrity_hash = artifact_integrity_hash
        self.sealed_at = datetime.now(timezone.utc)


class InterpretationSelection(Base):
    __tablename__ = "economic_interpretation_selections"

    id = _uuid_pk()
    interpretation_set_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_interpretation_sets.id"), nullable=False
    )
    source_lineage_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_source_lineages.id"), nullable=False
    )
    evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id"), nullable=False
    )
    selected_classification_attempt_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_classification_attempts.id"), nullable=False
    )
    pinned_evidence_revision_ordinal = Column(Integer, nullable=False)
    interpretation_override_revision_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_interpretation_override_revisions.id")
    )
    social_association_revision_ref_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_social_association_revision_refs.id")
    )
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "interpretation_set_id",
            "source_lineage_id",
            name="uq_economic_interpretation_selection_lineage",
        ),
    )


class ThemeObservation(Base):
    __tablename__ = "economic_theme_observations"

    id = _uuid_pk()
    claim_assignment_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_claim_assignments.id"), nullable=False
    )
    observation_kind = Column(String(40), nullable=False)
    evidence_channel = Column(String(40), nullable=False)
    derivation_policy_version = Column(String(120), nullable=False)
    observed_at = Column(DateTime(timezone=True))
    available_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "claim_assignment_id",
            "observation_kind",
            "evidence_channel",
            "derivation_policy_version",
            name="uq_economic_theme_observation_identity",
        ),
    )


class ThemeConstituentExposure(Base):
    __tablename__ = "economic_theme_constituent_exposures"

    id = _uuid_pk()
    claim_assignment_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_claim_assignments.id"), nullable=False
    )
    security_id = Column(Integer, ForeignKey("stock_universe.id"), nullable=False)
    exposure_kind = Column(String(40), nullable=False)
    exposure_strength = Column(Float)
    derivation_policy_version = Column(String(120), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "claim_assignment_id",
            "security_id",
            "exposure_kind",
            "derivation_policy_version",
            name="uq_economic_theme_constituent_exposure_identity",
        ),
    )


class ThemeSignalObservation(Base):
    __tablename__ = "economic_theme_signal_observations"

    id = _uuid_pk()
    claim_assignment_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_claim_assignments.id"), nullable=False
    )
    security_id = Column(Integer, ForeignKey("stock_universe.id"))
    signal_kind = Column(String(80), nullable=False)
    signal_policy_version = Column(String(120), nullable=False)
    observed_at = Column(DateTime(timezone=True))
    available_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "claim_assignment_id",
            "security_id",
            "signal_kind",
            "signal_policy_version",
            name="uq_economic_theme_signal_observation_identity",
        ),
    )


class EconomicThemeEmbedding(Base):
    __tablename__ = "economic_theme_embeddings"

    id = _uuid_pk()
    economic_theme_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_themes.id"), nullable=False
    )
    taxonomy_semantic_hash = Column(String(128), nullable=False)
    source_text_hash = Column(String(128), nullable=False)
    embedding_model = Column(String(120), nullable=False)
    model_version = Column(String(120), nullable=False)
    embedding = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "economic_theme_id",
            "taxonomy_semantic_hash",
            "source_text_hash",
            "embedding_model",
            "model_version",
            name="uq_economic_theme_embedding_cache_key",
        ),
    )


class MetricsRevision(Base):
    __tablename__ = "economic_metrics_revisions"

    id = _uuid_pk()
    status = Column(String(16), nullable=False, default="unsealed")
    interpretation_set_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_interpretation_sets.id"), nullable=False
    )
    formula_version = Column(String(120), nullable=False)
    as_of = Column(DateTime(timezone=True), nullable=False)
    semantic_hash = Column(String(128))
    artifact_integrity_hash = Column(String(128))
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()
    sealed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('unsealed','sealed')", name="ck_economic_metrics_revision_status"
        ),
        UniqueConstraint(
            "interpretation_set_id",
            "formula_version",
            "as_of",
            name="uq_economic_metrics_revision_key",
        ),
    )

    def seal(self, *, semantic_hash: str, artifact_integrity_hash: str) -> None:
        if self.status != "unsealed":
            raise ImmutableRuntimePayload("sealed_payload_immutable")
        self.status = "sealed"
        self.semantic_hash = semantic_hash
        self.artifact_integrity_hash = artifact_integrity_hash
        self.sealed_at = datetime.now(timezone.utc)


class ThemeMetric(Base):
    __tablename__ = "economic_theme_metrics"

    id = _uuid_pk()
    metrics_revision_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_metrics_revisions.id"), nullable=False
    )
    economic_theme_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_themes.id"), nullable=False
    )
    ranking_view = Column(String(80), nullable=False)
    available = Column(Boolean, nullable=False)
    raw_value = Column(Float)
    percentile = Column(Float)
    components = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "metrics_revision_id",
            "economic_theme_id",
            "ranking_view",
            name="uq_economic_theme_metric_identity",
        ),
    )


APPEND_ONLY_RUNTIME_MODELS = (
    SourceFamily,
    SourceLineage,
    EvidencePacket,
    EvidencePrecedenceRevision,
    LensEligibilityRevision,
    ProcessingRequest,
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
)

SEALED_RUNTIME_MODELS = (InterpretationSet, MetricsRevision)

ECONOMIC_TAXONOMY_RUNTIME_TABLES = [
    SourceFamily.__table__,
    SourceLineage.__table__,
    EvidencePacket.__table__,
    EvidencePrecedenceRevision.__table__,
    LensEligibilityRevision.__table__,
    ProcessingRequest.__table__,
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

    changed = {
        attr.key
        for attr in state.mapper.column_attrs
        if state.attrs[attr.key].history.has_changes()
    }
    permitted = {"status", "semantic_hash", "artifact_integrity_hash", "sealed_at"}
    if row.status != "sealed" or not changed.issubset(permitted):
        raise ImmutableRuntimePayload("runtime_payload_immutable")
    if not row.semantic_hash or not row.artifact_integrity_hash or row.sealed_at is None:
        raise ImmutableRuntimePayload("sealed_payload_incomplete")


@event.listens_for(Session, "before_flush")
def _protect_economic_taxonomy_runtime(session, _flush_context, _instances):
    _allocate_evidence_ordinals(session)

    for row in session.deleted:
        if isinstance(row, APPEND_ONLY_RUNTIME_MODELS + SEALED_RUNTIME_MODELS):
            raise ImmutableRuntimePayload("runtime_payload_immutable")

    for row in session.dirty:
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
    """
).execute_if(dialect="postgresql")

event.listen(SourceFamily.__table__, "after_create", _CREATE_RUNTIME_TRIGGER_FUNCTIONS)

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
