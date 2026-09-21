"""Immutable runtime evidence, interpretation, and metrics persistence.

The semantic taxonomy is versioned separately in :mod:`economic_taxonomy`.
This module records the evidence and processing history used to interpret that
taxonomy.  Rows are append-only; the two aggregate payloads are built while
unsealed and allow one audited transition to ``sealed``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
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
from app.models.economic_taxonomy import TaxonomyVersion


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
    status = Column(String(32), nullable=False, default="pending")
    available_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    lease_token = Column(Uuid(as_uuid=True))
    lease_owner = Column(String(200))
    lease_expires_at = Column(DateTime(timezone=True))
    observed_processing_head_revision = Column(Integer)
    observed_authority_epoch = Column(Integer)
    completion_code = Column(String(80))
    result_payload = Column(JSON)
    created_at = _created_at()
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "policy_bundle_version",
            name="uq_economic_processing_request_identity",
        ),
        CheckConstraint(
            "status IN ('pending','leased','retryable','completed','terminal_failure')",
            name="ck_economic_processing_request_status",
        ),
        CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL "
            "AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'leased' AND lease_token IS NULL "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_economic_processing_request_lease_shape",
        ),
    )


class ProcessingRequestEvent(Base):
    __tablename__ = "economic_processing_request_events"

    id = _uuid_pk()
    processing_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_processing_requests.id"),
        nullable=False,
    )
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(String(80), nullable=False)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "processing_request_id",
            "sequence_number",
            name="uq_economic_processing_request_event_sequence",
        ),
    )


class ProviderAttempt(Base):
    __tablename__ = "economic_provider_attempts"

    id = _uuid_pk()
    logical_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_processing_requests.id"),
        nullable=False,
    )
    operation_kind = Column(String(80), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    dispatch_id = Column(String(200), nullable=False)
    created_at = _created_at()

    events = relationship(
        "ProviderAttemptEvent",
        order_by="ProviderAttemptEvent.sequence_number",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "logical_request_id",
            "operation_kind",
            "attempt_number",
            name="uq_economic_provider_attempt_number",
        ),
        UniqueConstraint(
            "logical_request_id",
            "operation_kind",
            "dispatch_id",
            name="uq_economic_provider_attempt_dispatch",
        ),
    )

    @property
    def outcome(self) -> str | None:
        return self.events[-1].outcome if self.events else None


class ProviderAttemptEvent(Base):
    __tablename__ = "economic_provider_attempt_events"

    id = _uuid_pk()
    provider_attempt_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_provider_attempts.id"), nullable=False
    )
    sequence_number = Column(Integer, nullable=False)
    outcome = Column(String(40), nullable=False)
    result_artifact_id = Column(Uuid(as_uuid=True))
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "provider_attempt_id",
            "sequence_number",
            name="uq_economic_provider_attempt_event_sequence",
        ),
        CheckConstraint(
            "outcome IN ('success','retryable_failure','uncertain','terminal_failure')",
            name="ck_economic_provider_attempt_event_outcome",
        ),
        CheckConstraint(
            "(outcome = 'success' AND result_artifact_id IS NOT NULL) OR "
            "(outcome <> 'success' AND result_artifact_id IS NULL)",
            name="ck_economic_provider_attempt_result_shape",
        ),
    )


class EconomicExposureCandidate(Base):
    __tablename__ = "economic_exposure_candidates"

    id = _uuid_pk()
    processing_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_processing_requests.id"),
        nullable=False,
    )
    candidate_key = Column(String(160), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "processing_request_id",
            "candidate_key",
            name="uq_economic_exposure_candidate_key",
        ),
    )


class DimensionProposal(Base):
    __tablename__ = "economic_dimension_proposals"

    id = _uuid_pk()
    processing_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_processing_requests.id"),
        nullable=False,
    )
    dimension_key = Column(String(120), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "processing_request_id",
            "dimension_key",
            name="uq_economic_dimension_proposal_key",
        ),
    )


class NamingProposal(Base):
    __tablename__ = "economic_naming_proposals"

    id = _uuid_pk()
    processing_request_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_processing_requests.id"),
        nullable=False,
    )
    proposal_key = Column(String(160), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "processing_request_id",
            "proposal_key",
            name="uq_economic_naming_proposal_key",
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
    generation_input_manifest_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_generation_input_manifests.id")
    )
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
    generation_input_manifest_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_generation_input_manifests.id")
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


class TaxonomySourceRevisionLog(Base):
    __tablename__ = "taxonomy_source_revision_log"

    id = _uuid_pk()
    producer_kind = Column(String(80), nullable=False)
    logical_source_key = Column(String(500), nullable=False)
    revision_kind = Column(String(80), nullable=False)
    revision_number = Column(Integer, nullable=False)
    content_hash = Column(String(128), nullable=False)
    authority_epoch = Column(Integer, nullable=False)
    committed_at = _created_at()

    __table_args__ = (
        UniqueConstraint(
            "producer_kind",
            "logical_source_key",
            "revision_kind",
            "revision_number",
            name="uq_taxonomy_source_revision_identity",
        ),
    )


class SemanticInvalidationRevision(Base):
    __tablename__ = "economic_semantic_invalidation_revisions"

    id = _uuid_pk()
    revision_number = Column(Integer, nullable=False, unique=True)
    reason = Column(Text, nullable=False)
    created_by = Column(String(200), nullable=False)
    created_at = _created_at()


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
        Uuid(as_uuid=True), ForeignKey("economic_interpretation_sets.id"), nullable=False
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
        Uuid(as_uuid=True), ForeignKey("economic_serving_generations.id"), nullable=False
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
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_taxonomy_authority_singleton"),
        CheckConstraint(
            "mode IN ('legacy','shadow','dual','economic')",
            name="ck_taxonomy_authority_mode",
        ),
    )


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
    SemanticInvalidationRevision,
    ReaderCapabilityManifest,
    ServingGeneration,
    ServingGenerationEvent,
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
    SemanticInvalidationRevision.__table__,
    ReaderCapabilityManifest.__table__,
    GenerationInputManifest.__table__,
    ReaderSnapshotBundle.__table__,
    ServingGeneration.__table__,
    ServingGenerationEvent.__table__,
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
    if not row.semantic_hash or not row.artifact_integrity_hash or row.sealed_at is None:
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
