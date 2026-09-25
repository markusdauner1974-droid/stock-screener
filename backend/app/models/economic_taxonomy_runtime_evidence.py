"""Evidence, processing, interpretation, and metric runtime records."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
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
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.economic_taxonomy_runtime_common import (
    ImmutableRuntimePayload,
    _created_at,
    _uuid_pk,
)


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
        Uuid(as_uuid=True),
        ForeignKey("economic_extraction_artifacts.id"),
        nullable=False,
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
        Uuid(as_uuid=True),
        ForeignKey("economic_processing_requests.id"),
        nullable=False,
    )
    claim_review_artifact_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_claim_review_artifacts.id"),
        nullable=False,
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
        Uuid(as_uuid=True),
        ForeignKey("economic_classification_attempts.id"),
        nullable=False,
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
        Uuid(as_uuid=True),
        ForeignKey("economic_classification_attempts.id"),
        nullable=False,
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
        Uuid(as_uuid=True),
        ForeignKey("economic_interpretation_sets.id"),
        nullable=False,
    )
    source_lineage_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_source_lineages.id"), nullable=False
    )
    evidence_packet_id = Column(
        Uuid(as_uuid=True), ForeignKey("economic_evidence_packets.id"), nullable=False
    )
    selected_classification_attempt_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_classification_attempts.id"),
        nullable=False,
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
        Uuid(as_uuid=True),
        ForeignKey("economic_interpretation_sets.id"),
        nullable=False,
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
            "status IN ('unsealed','sealed')",
            name="ck_economic_metrics_revision_status",
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


__all__ = (
    "ClaimAssignment",
    "ClaimReviewArtifact",
    "ClassificationAttempt",
    "ClassificationAttemptEvent",
    "ConstituentDecisionRevision",
    "DevelopmentSelectionRevision",
    "DimensionProposal",
    "EconomicExposureCandidate",
    "EconomicThemeEmbedding",
    "EvidencePacket",
    "EvidencePrecedenceRevision",
    "ExtractionArtifact",
    "InterpretationOverrideRevision",
    "InterpretationSelection",
    "InterpretationSet",
    "LensEligibilityRevision",
    "MetricsRevision",
    "NamingProposal",
    "ProcessingRequest",
    "ProcessingRequestEvent",
    "ProposalDecisionRevision",
    "ProviderAttempt",
    "ProviderAttemptEvent",
    "SocialAssociationRevisionRef",
    "SourceFamily",
    "SourceLineage",
    "TaxonomySourceRevisionLog",
    "ThemeConstituentExposure",
    "ThemeMetric",
    "ThemeObservation",
    "ThemeSignalObservation",
)
