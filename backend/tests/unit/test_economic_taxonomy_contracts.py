import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from app.domain.economic_taxonomy.contracts import (
    AdminPrincipal,
    AuthorityMode,
    ClaimReviewArtifactKey,
    ClassificationAttemptEvent,
    ClassificationAttemptKey,
    DevelopmentSupport,
    EvidenceChannel,
    EvidencePacketDescriptor,
    EvidencePrecedenceDecision,
    ExposureSupport,
    ExtractionArtifactKey,
    FACET_CATALOG_SEMANTIC_FIELDS,
    FailureCode,
    GenerationInputSelection,
    InterpretationCandidate,
    LIFECYCLE_POLICY_V1,
    METRICS_POLICY_V1,
    ProcessingRequestKey,
    ProjectionKey,
    ProviderAttemptKey,
    ProviderAttemptOutcome,
    ProviderAttemptRecord,
    RankingView,
    ServingGenerationEvent,
    SocialAssociationRevisionRef,
    SourceLineageKey,
)
from app.domain.economic_taxonomy.policy import (
    choose_interpretation,
    decide_evidence_precedence,
    projection_is_deliverable,
    reconcile_social_decisions,
    relationship_from_proposed,
    validate_split_allocations,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "economic_taxonomy"


def _candidate(
    attempt_id: str,
    *,
    status: str = "completed",
    ordinal: int = 1,
    provider_order: int | None = None,
    assignments: tuple[str, ...] = ("theme-1",),
    precedence_state: str = "effective",
) -> InterpretationCandidate:
    return InterpretationCandidate(
        attempt_id=attempt_id,
        status=status,
        evidence_revision_ordinal=ordinal,
        provider_revision_order=provider_order,
        assignments=assignments,
        precedence_state=precedence_state,
    )


def test_h10_and_h11_are_distinct_attempts_but_reuse_review_artifact():
    lineage = SourceLineageKey(canonical_source_family="provider:post:42")
    request = ProcessingRequestKey(
        source_lineage=lineage,
        evidence_packet_id="p5",
        policy_bundle_version="v1",
    )
    review = ClaimReviewArtifactKey(
        extraction_artifact_id="x1",
        claim_review_policy_version="review-v1",
        facet_catalog_semantic_hash="facets-v1",
    )
    h10 = ClassificationAttemptKey(
        claim_review_artifact_id=review,
        input_taxonomy_version_id="H10",
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
    )
    h11 = ClassificationAttemptKey(
        claim_review_artifact_id=review,
        input_taxonomy_version_id="H11",
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
    )

    assert request.policy_bundle_version == "v1"
    assert h10 != h11
    assert h10.claim_review_artifact_id == h11.claim_review_artifact_id == review


def test_artifact_keys_reuse_only_exact_inputs():
    extraction = ExtractionArtifactKey("packet-1", "extract-v1")
    first = ClaimReviewArtifactKey(extraction, "review-v1", "facets-v1")
    definition_changed = ClaimReviewArtifactKey(extraction, "review-v1", "facets-v2")

    assert first != definition_changed
    assert extraction == ExtractionArtifactKey("packet-1", "extract-v1")


def test_later_effective_provider_revision_wins_when_older_attempt_finishes_late():
    correction = _candidate(
        "correction", provider_order=5, ordinal=5, assignments=()
    )
    delayed_old = _candidate(
        "delayed-old", provider_order=4, ordinal=4, assignments=("ai-memory",)
    )

    assert choose_interpretation(
        previous=None, candidates=(correction, delayed_old)
    ) == correction


def test_successful_empty_supersedes_old_interpretation():
    old = _candidate("old", ordinal=1, assignments=("ai-memory",))
    empty = _candidate("empty", ordinal=2, assignments=())

    assert choose_interpretation(previous=old, candidates=(empty,)) == empty


def test_failed_or_held_reprocessing_retains_previous_interpretation():
    accepted = _candidate("accepted")
    failed = _candidate("failed", status="failed", ordinal=2)
    held = _candidate("held", ordinal=3, precedence_state="hold_review")

    assert choose_interpretation(
        previous=accepted, candidates=(failed, held)
    ) == accepted


def test_authenticated_override_can_select_an_older_completed_attempt():
    older = _candidate("older", ordinal=1)
    newer = _candidate("newer", ordinal=2)
    principal = AdminPrincipal(
        subject="admin:taxonomy-reviewer",
        auth_method="admin_api_key",
        roles=frozenset({"taxonomy:review"}),
    )

    assert choose_interpretation(
        previous=None,
        candidates=(newer, older),
        override_attempt_id="older",
        override_principal=principal,
    ) == older


def test_unauthenticated_override_is_rejected():
    with pytest.raises(PermissionError, match="authenticated taxonomy reviewer"):
        choose_interpretation(
            previous=None,
            candidates=(_candidate("attempt-1"),),
            override_attempt_id="attempt-1",
            override_principal=None,
        )


def test_route_ids_do_not_change_ordinary_lineage():
    key = SourceLineageKey(canonical_source_family="provider:post:42")

    assert {field.name for field in fields(key)} == {
        "canonical_source_family",
        "scope_suffix",
        "admission_policy_key",
    }
    assert "route" not in key.__dataclass_fields__


def test_scoped_lineage_requires_governed_non_overlapping_policy():
    with pytest.raises(ValueError, match="admission_policy_key"):
        SourceLineageKey(
            canonical_source_family="provider:post:42", scope_suffix="attachment:1"
        )

    key = SourceLineageKey(
        canonical_source_family="provider:post:42",
        scope_suffix="attachment:1",
        admission_policy_key="non-overlap-v1",
    )
    assert key.scope_suffix == "attachment:1"


def test_late_archive_cannot_supersede_corrected_empty_without_source_precedence():
    accepted = EvidencePacketDescriptor(
        packet_id="p5",
        evidence_content_fingerprint="empty-v5",
        provider_revision_id="5",
        provider_revision_order=5,
        attachment_hashes=frozenset(),
    )
    candidate = EvidencePacketDescriptor(
        packet_id="p6",
        evidence_content_fingerprint="older-archive",
        captured_from="late_archive",
        attachment_hashes=frozenset(),
    )

    assert (
        decide_evidence_precedence(accepted=accepted, candidate=candidate)
        == EvidencePrecedenceDecision.HOLD_REVIEW
    )


def test_less_complete_recapture_does_not_withdraw_attachment_evidence():
    accepted = EvidencePacketDescriptor(
        packet_id="p5",
        evidence_content_fingerprint="with-attachment",
        provider_revision_id="5",
        provider_revision_order=5,
        attachment_hashes=frozenset({"a1"}),
    )
    candidate = EvidencePacketDescriptor(
        packet_id="p6",
        evidence_content_fingerprint="missing-attachment",
        attachment_hashes=frozenset(),
    )

    assert (
        decide_evidence_precedence(accepted=accepted, candidate=candidate)
        == EvidencePrecedenceDecision.HOLD_REVIEW
    )


def test_authoritative_provider_order_or_explicit_supersession_controls_precedence():
    accepted = EvidencePacketDescriptor(
        packet_id="p4",
        evidence_content_fingerprint="v4",
        provider_revision_id="4",
        provider_revision_order=4,
    )
    ordered = EvidencePacketDescriptor(
        packet_id="p5",
        evidence_content_fingerprint="v5",
        provider_revision_id="5",
        provider_revision_order=5,
    )
    explicit = EvidencePacketDescriptor(
        packet_id="corrected",
        evidence_content_fingerprint="corrected-empty",
        supersedes_packet_id="p4",
    )

    assert decide_evidence_precedence(accepted, ordered) == EvidencePrecedenceDecision.ADVANCE
    assert decide_evidence_precedence(accepted, explicit) == EvidencePrecedenceDecision.ADVANCE


def test_equivalent_content_is_reused_without_losing_route_provenance():
    accepted = EvidencePacketDescriptor(
        packet_id="legacy-packet",
        evidence_content_fingerprint="content-sha256",
        captured_from="legacy",
    )
    social = EvidencePacketDescriptor(
        packet_id="social-packet",
        evidence_content_fingerprint="content-sha256",
        captured_from="social",
    )

    assert (
        decide_evidence_precedence(accepted, social)
        == EvidencePrecedenceDecision.REUSE_EQUIVALENT
    )


def test_retryable_failure_is_attempt_history_not_reusable_artifact():
    first = ProviderAttemptRecord(
        key=ProviderAttemptKey("request:p5:v1", "extract", 1),
        outcome=ProviderAttemptOutcome.RETRYABLE_FAILURE,
        result_artifact_id=None,
    )
    second = ProviderAttemptRecord(
        key=ProviderAttemptKey("request:p5:v1", "extract", 2),
        outcome=ProviderAttemptOutcome.SUCCESS,
        result_artifact_id="artifact-1",
    )

    assert first.key != second.key
    assert first.result_artifact_id is None
    assert second.result_artifact_id == "artifact-1"


def test_uncertain_and_known_retryable_provider_outcomes_stay_distinct():
    assert ProviderAttemptOutcome.UNCERTAIN != ProviderAttemptOutcome.RETRYABLE_FAILURE
    assert FailureCode.PROVIDER_OUTCOME_UNCERTAIN.value == "provider_outcome_uncertain"


def test_social_pair_identity_allows_numbered_revision_history():
    accepted = SocialAssociationRevisionRef("a1", 1)
    rejected = SocialAssociationRevisionRef("a1", 2)

    assert accepted != rejected
    with pytest.raises(FrozenInstanceError):
        accepted.revision_number = 3


def test_projection_delivery_is_derived_from_publication_history():
    assert projection_is_deliverable(ServingGenerationEvent.PUBLISHED) is True
    assert projection_is_deliverable(ServingGenerationEvent.SUPERSEDED) is False
    assert projection_is_deliverable(ServingGenerationEvent.ABANDONED) is False


def test_generation_selection_pins_all_auxiliary_revisions():
    selection = GenerationInputSelection(
        lineage="post:42",
        evidence_packet_id="packet-5",
        selected_attempt_id="attempt-3",
        eligibility_revision=4,
        evidence_precedence_revision=5,
        interpretation_override_revision_id=None,
        constituent_decision_revision=6,
        social_association_revision=SocialAssociationRevisionRef("a1", 2),
        social_decision_revision=7,
        development_revision=8,
        mapping_revision=9,
        metrics_policy_revision=10,
        compatibility_projection_revision=11,
    )

    assert selection.evidence_precedence_revision == 5
    assert selection.social_association_revision.revision_number == 2
    with pytest.raises(FrozenInstanceError):
        selection.mapping_revision = 12


def test_split_requires_every_claim_exactly_once_or_reviewed_excluded():
    complete = validate_split_allocations(
        claim_ids={1, 2, 3},
        allocations={1: "petroleum", 2: "metals"},
        reviewed_exclusions={3},
    )
    duplicate = validate_split_allocations(
        claim_ids={1, 2}, allocations={1: ("petroleum", "metals"), 2: "metals"}
    )

    assert complete.complete is True
    assert duplicate.complete is False
    assert duplicate.multiply_allocated_claim_ids == frozenset({1})


def test_social_accept_reject_conflict_blocks_membership():
    result = reconcile_social_decisions(("accepted", "rejected"))

    assert result.state == "conflict_review_required"
    assert result.live is False


def test_social_unanimous_acceptance_is_live_but_proposed_is_not():
    assert reconcile_social_decisions(("accepted", "accepted")).live is True
    assert reconcile_social_decisions(("proposed",)).live is False


def test_relationship_direction_is_from_proposed_to_existing():
    assert relationship_from_proposed("Copper", "Copper Miners") == "broader"
    assert relationship_from_proposed("Copper Miners", "Copper") == "narrower"


def test_logical_projection_identity_ignores_attempt_epoch():
    key = ProjectionKey(
        source_lineage="post:1",
        projection_revision=2,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
    )

    assert "authority_epoch" not in key.__dataclass_fields__


def test_shared_enum_values_are_exact_and_fundamental_view_is_unsigned():
    assert {item.value for item in AuthorityMode} == {
        "legacy",
        "shadow",
        "dual",
        "economic",
    }
    assert {item.value for item in EvidenceChannel} == {
        "technical",
        "fundamental",
        "narrative",
    }
    assert {item.value for item in ExposureSupport} == {
        "direct",
        "inferred",
        "unsupported",
        "unresolved",
    }
    assert {item.value for item in DevelopmentSupport} == {
        "present",
        "absent",
        "unresolved",
    }
    assert RankingView.FUNDAMENTAL_ATTENTION.value == "fundamental_attention"
    assert "fundamental_momentum" not in {item.value for item in RankingView}


def test_attempt_generation_and_failure_state_machines_are_exact():
    assert {item.value for item in ClassificationAttemptEvent} == {
        "started",
        "completed",
        "failed",
        "superseded_before_acceptance",
    }
    assert {item.value for item in ServingGenerationEvent} == {
        "prepared",
        "published",
        "superseded",
        "abandoned",
    }
    assert {item.value for item in FailureCode} == {
        "invalid_schema",
        "unsupported_composition",
        "unknown_dimension",
        "requires_naming_review",
        "ambiguous_identity",
        "stale_processing_head",
        "stale_authority_epoch",
        "stale_projection_revision",
        "authorization_required",
        "budget_exhausted",
        "conflict_review_required",
        "compatibility_pending",
        "reader_not_ready",
        "manifest_changed",
        "publication_validation_failed",
        "rollback_recovery_required",
        "provider_retryable",
        "provider_outcome_uncertain",
        "provider_terminal",
    }


def test_v1_lifecycle_and_metric_policy_values_are_frozen():
    assert LIFECYCLE_POLICY_V1.provisional_direct_roots == 3
    assert LIFECYCLE_POLICY_V1.provisional_source_families == 2
    assert LIFECYCLE_POLICY_V1.provisional_dates == 2
    assert LIFECYCLE_POLICY_V1.provisional_window_days == 30
    assert LIFECYCLE_POLICY_V1.provisional_security_breadth == 2
    assert LIFECYCLE_POLICY_V1.dormancy_days == 90
    assert LIFECYCLE_POLICY_V1.reactivation_roots == 2
    assert LIFECYCLE_POLICY_V1.reactivation_families == 2
    assert LIFECYCLE_POLICY_V1.reactivation_window_days == 14
    assert LIFECYCLE_POLICY_V1.reactivated_uses_dormancy_rule is True

    assert METRICS_POLICY_V1.technical_window_days == 30
    assert METRICS_POLICY_V1.technical_root_half_life_days == 7
    assert METRICS_POLICY_V1.technical_signal_half_life_days == 5
    assert METRICS_POLICY_V1.technical_signal_weight == 1.0
    assert METRICS_POLICY_V1.fundamental_window_days == 90
    assert METRICS_POLICY_V1.fundamental_half_life_days == 30
    assert METRICS_POLICY_V1.narrative_window_days == 14
    assert METRICS_POLICY_V1.narrative_half_life_days == 3
    assert METRICS_POLICY_V1.closed_windows is True
    assert METRICS_POLICY_V1.missing_is_unavailable is True
    assert METRICS_POLICY_V1.single_theme_percentile == 100


def test_facet_catalog_hash_includes_dimension_meaning_not_only_keys():
    assert {
        "definition",
        "inclusion_semantics",
        "exclusion_semantics",
    }.issubset(FACET_CATALOG_SEMANTIC_FIELDS)


def test_named_contract_fixture_executes_every_counterexample():
    payload = json.loads((FIXTURES / "contract_cases.json").read_text())
    assert payload["schema_version"] == 1
    assert {case["name"] for case in payload["cases"]} == {
        "late_archive_after_corrected_empty",
        "partial_recapture_missing_attachment",
        "provider_revision_advance",
        "route_equivalent_content",
        "social_accept_reject_conflict",
        "proposed_copper_is_broader",
    }

    actual = {}
    for case in payload["cases"]:
        if case["kind"] == "precedence":
            accepted = EvidencePacketDescriptor(**case["accepted"])
            candidate = EvidencePacketDescriptor(**case["candidate"])
            actual[case["name"]] = decide_evidence_precedence(
                accepted, candidate
            ).value
        elif case["kind"] == "social_decision":
            actual[case["name"]] = reconcile_social_decisions(
                tuple(case["decisions"])
            ).state
        else:
            actual[case["name"]] = relationship_from_proposed(
                case["proposed"], case["existing"]
            )

    assert actual == {case["name"]: case["expected"] for case in payload["cases"]}
