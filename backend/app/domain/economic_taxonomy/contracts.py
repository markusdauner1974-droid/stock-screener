"""Shared economic-taxonomy contracts.

These value objects freeze the boundaries used by persistence, processing,
publication, compatibility delivery, and readers before any of those layers
exist.  They deliberately keep identities for source lineage, processing
requests, reusable provider results, exact classification attempts, Social
association revisions, and logical projections separate.

The persistence model built on these contracts follows these rules:

* semantic snapshots and serving payloads are immutable after sealing;
  operational state changes are append-only events;
* admission ordinal is an audit order, not evidence freshness; effective
  precedence requires provider revision metadata, an explicit relation, or
  review;
* provider attempts are append-only, while only successful terminal result
  artifacts are reusable;
* a serving generation pins every auxiliary revision in
  :class:`GenerationInputSelection` and advances from a bounded committed
  cutoff only when its parent and semantic-invalidation revision still match;
* projection payloads replace one lineage's complete contribution.  Logical
  identity excludes authority epoch and targets reject older revisions;
* stable Social membership identity is separate from append-only numbered
  association and decision revisions;
* proposals and interpretation overrides are append-only revision streams;
* embeddings are a rebuildable retrieval cache, never an identity authority;
* semantic writes bind to an authenticated administrator or the fixed
  ``system:economic-taxonomy-refresh`` service principal; and
* facet-catalog semantic hashes include the dimension definition and its
  inclusion/exclusion semantics, not only the dimension key.

V1 lifecycle and metric constants are represented below as frozen values so
later services cannot silently choose different thresholds or score meanings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AuthorityMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    DUAL = "dual"
    ECONOMIC = "economic"


class EvidenceChannel(StrEnum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    NARRATIVE = "narrative"


class ExposureSupport(StrEnum):
    DIRECT = "direct"
    INFERRED = "inferred"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"


class DevelopmentSupport(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"


class EvidencePrecedenceDecision(StrEnum):
    ADVANCE = "advance"
    REUSE_EQUIVALENT = "reuse_equivalent"
    IGNORE_SUPERSEDED = "ignore_superseded"
    HOLD_REVIEW = "hold_review"


class ProviderAttemptOutcome(StrEnum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    UNCERTAIN = "uncertain"
    TERMINAL_FAILURE = "terminal_failure"


class ClassificationAttemptEvent(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED_BEFORE_ACCEPTANCE = "superseded_before_acceptance"


class ServingGenerationEvent(StrEnum):
    PREPARED = "prepared"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ABANDONED = "abandoned"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class SourceLineageKey:
    """Route-independent correction stream for one canonical source family."""

    canonical_source_family: str
    scope_suffix: str | None = None
    admission_policy_key: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.canonical_source_family, "canonical_source_family")
        if self.scope_suffix is not None:
            _require_text(self.scope_suffix, "scope_suffix")
            if self.admission_policy_key is None:
                raise ValueError(
                    "scope_suffix requires an admission_policy_key proving a "
                    "non-overlapping evidence scope"
                )
        if self.admission_policy_key is not None:
            _require_text(self.admission_policy_key, "admission_policy_key")


@dataclass(frozen=True, slots=True)
class ExtractionArtifactKey:
    evidence_packet_id: str
    extraction_policy_version: str

    def __post_init__(self) -> None:
        _require_text(self.evidence_packet_id, "evidence_packet_id")
        _require_text(self.extraction_policy_version, "extraction_policy_version")


@dataclass(frozen=True, slots=True)
class SocialAssociationRevisionRef:
    association_id: str
    revision_number: int

    def __post_init__(self) -> None:
        _require_text(self.association_id, "association_id")
        _require_positive(self.revision_number, "revision_number")


@dataclass(frozen=True, slots=True)
class GenerationInputSelection:
    """One lineage entry in a complete immutable generation-input manifest."""

    lineage: str
    evidence_packet_id: str
    selected_attempt_id: str | None
    eligibility_revision: int
    evidence_precedence_revision: int
    interpretation_override_revision_id: str | None
    constituent_decision_revision: int | None
    social_association_revision: SocialAssociationRevisionRef | None
    social_decision_revision: int | None
    development_revision: int | None
    mapping_revision: int
    metrics_policy_revision: int
    compatibility_projection_revision: int

    def __post_init__(self) -> None:
        _require_text(self.lineage, "lineage")
        _require_text(self.evidence_packet_id, "evidence_packet_id")
        if self.selected_attempt_id is not None:
            _require_text(self.selected_attempt_id, "selected_attempt_id")
        if self.interpretation_override_revision_id is not None:
            _require_text(
                self.interpretation_override_revision_id,
                "interpretation_override_revision_id",
            )
        for name in (
            "eligibility_revision",
            "evidence_precedence_revision",
            "mapping_revision",
            "metrics_policy_revision",
            "compatibility_projection_revision",
        ):
            _require_positive(getattr(self, name), name)
        for name in (
            "constituent_decision_revision",
            "social_decision_revision",
            "development_revision",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_positive(value, name)


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    subject: str
    auth_method: str
    roles: frozenset[str]

    def __post_init__(self) -> None:
        _require_text(self.subject, "subject")
        _require_text(self.auth_method, "auth_method")
        object.__setattr__(self, "roles", frozenset(self.roles))
        if any(not role.strip() for role in self.roles):
            raise ValueError("roles must contain only non-empty values")

    @property
    def can_review_taxonomy(self) -> bool:
        return "taxonomy:review" in self.roles


@dataclass(frozen=True, slots=True)
class EvidencePacketDescriptor:
    """Minimum immutable evidence metadata needed by precedence policy."""

    packet_id: str
    evidence_content_fingerprint: str
    provider_revision_id: str | None = None
    provider_revision_order: int | None = None
    supersedes_packet_id: str | None = None
    equivalent_to_packet_id: str | None = None
    captured_from: str | None = None
    attachment_hashes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_text(self.packet_id, "packet_id")
        _require_text(
            self.evidence_content_fingerprint, "evidence_content_fingerprint"
        )
        for name in (
            "provider_revision_id",
            "supersedes_packet_id",
            "equivalent_to_packet_id",
            "captured_from",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        if self.provider_revision_order is not None:
            _require_positive(
                self.provider_revision_order, "provider_revision_order"
            )
        object.__setattr__(self, "attachment_hashes", frozenset(self.attachment_hashes))
        if any(not value.strip() for value in self.attachment_hashes):
            raise ValueError("attachment_hashes must contain non-empty values")


@dataclass(frozen=True, slots=True)
class InterpretationCandidate:
    attempt_id: str
    status: str
    evidence_revision_ordinal: int
    provider_revision_order: int | None = None
    assignments: tuple[str, ...] = ()
    precedence_state: str = "effective"

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.status, "status")
        _require_positive(
            self.evidence_revision_ordinal, "evidence_revision_ordinal"
        )
        if self.provider_revision_order is not None:
            _require_positive(
                self.provider_revision_order, "provider_revision_order"
            )
        object.__setattr__(self, "assignments", tuple(self.assignments))
        _require_text(self.precedence_state, "precedence_state")


@dataclass(frozen=True, slots=True)
class SocialDecisionResult:
    state: str
    live: bool


@dataclass(frozen=True, slots=True)
class LifecyclePolicyV1:
    provisional_direct_roots: int = 3
    provisional_source_families: int = 2
    provisional_dates: int = 2
    provisional_window_days: int = 30
    provisional_security_breadth: int = 2
    dormancy_days: int = 90
    reactivation_roots: int = 2
    reactivation_families: int = 2
    reactivation_window_days: int = 14
    reactivated_uses_dormancy_rule: bool = True
    retirement_requires_review: bool = True


@dataclass(frozen=True, slots=True)
class MetricsPolicyV1:
    technical_window_days: int = 30
    technical_root_half_life_days: int = 7
    technical_signal_half_life_days: int = 5
    technical_signal_weight: float = 1.0
    fundamental_window_days: int = 90
    fundamental_half_life_days: int = 30
    narrative_window_days: int = 14
    narrative_half_life_days: int = 3
    emerging_recent_days: int = 7
    emerging_prior_days: int = 21
    emerging_minimum_families: int = 2
    emerging_minimum_dates: int = 2
    broad_confirmation_minimum_channels: int = 2
    broad_confirmation_minimum_families: int = 2
    closed_windows: bool = True
    per_family_theme_utc_day_maximum: bool = True
    missing_is_unavailable: bool = True
    percentile_uses_average_rank: bool = True
    single_theme_percentile: int = 100


LIFECYCLE_POLICY_V1 = LifecyclePolicyV1()
METRICS_POLICY_V1 = MetricsPolicyV1()


FACET_CATALOG_SEMANTIC_FIELDS = frozenset(
    {
        "dimension_key",
        "definition",
        "inclusion_semantics",
        "exclusion_semantics",
        "value_type",
        "cardinality",
        "scope",
        "normalization_policy",
    }
)


GENERATION_INPUT_SELECTION_FIELDS = tuple(
    field.name for field in GenerationInputSelection.__dataclass_fields__.values()
)
