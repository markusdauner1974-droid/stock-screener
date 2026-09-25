from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select

from app.database import SessionLocal
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    ExtractionArtifact,
    GenerationInputManifest,
    InterpretationSelection,
    InterpretationSet,
    LensEligibilityRevision,
    MetricsRevision,
    ReaderCapabilityManifest,
    ReaderSnapshotBundle,
    ReaderSnapshotEntry,
    ServingGeneration,
    TaxonomyAuthority,
    ThemeConstituentExposure,
    ThemeObservation,
    ThemeSignalObservation,
)
from app.models.stock_universe import StockUniverse
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_seed import seed_initial_dimensions
from app.services.economic_taxonomy_snapshot_builder import (
    GenerationSnapshotInputs,
    build_snapshot_bundle,
)
from app.services.economic_theme_metrics_service import EconomicThemeMetricsService
from app.services.economic_theme_observation_service import (
    EconomicThemeObservationService,
    materialize_assignment_facts,
)

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


def _setup(db_session):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:author", reason="observation fixture")
    seed_initial_dimensions(repo, draft.id, actor="test:author")
    parent = repo.create_theme(
        draft.id,
        display_name="Copper",
        definition="Copper exposure.",
        mechanism="Copper economics",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
        actor="test:author",
    )
    child = repo.create_theme(
        draft.id,
        display_name="Copper Miners",
        definition="Copper mining exposure.",
        mechanism="Mine economics",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
        actor="test:author",
    )
    repo.add_specialization(
        draft.id, narrower=child.id, broader=parent.id, actor="test:author"
    )
    taxonomy = repo.seal_draft(draft.id)
    db_session.add_all(
        [
            TaxonomyAuthority(
                id=1,
                mode="shadow",
                processing_taxonomy_version_id=taxonomy.id,
                processing_head_revision=1,
                authority_epoch=1,
                writes_fenced=False,
                rollback_state="ready",
            ),
            StockUniverse(id=42, symbol="FCX", name="Freeport-McMoRan", market="US"),
        ]
    )
    db_session.commit()
    admitted = EconomicSourceAdmissionService(db_session).admit_content(
        EvidenceAdmission(
            provider="x",
            canonical_item_id="copper-post",
            capture_route="legacy",
            original_text="Copper miners broke out on stronger demand.",
            preparation_version="prep-v1",
            provider_revision_id="rev-1",
            provider_revision_order=1,
            grounding_snapshot={"companies": [{"security_id": 42, "symbol": "FCX"}]},
            captured_at=NOW,
            observed_at=NOW,
            available_at=NOW,
            evidence_channels=("fundamental", "narrative"),
        )
    )
    request = EconomicTaxonomyWorkRepository(db_session).enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )
    extraction = ExtractionArtifact(
        evidence_packet_id=admitted.packet_id,
        extraction_policy_version="extract-v1",
        result_status="accepted_candidates",
        result_payload={},
        provider_response_hash="extract",
    )
    db_session.add(extraction)
    db_session.flush()
    review = ClaimReviewArtifact(
        extraction_artifact_id=extraction.id,
        claim_review_policy_version="review-v1",
        facet_catalog_semantic_hash="facet-v1",
        result_status="accepted_candidates",
        result_payload={},
        provider_response_hash="review",
    )
    db_session.add(review)
    db_session.flush()
    attempt = ClassificationAttempt(
        processing_request_id=request.id,
        claim_review_artifact_id=review.id,
        input_taxonomy_version_id=taxonomy.id,
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
        result_status="completed",
        result_payload={},
    )
    db_session.add(attempt)
    db_session.flush()
    db_session.add(
        ClassificationAttemptEvent(
            classification_attempt_id=attempt.id,
            sequence_number=1,
            event_type="completed",
            event_payload={},
        )
    )
    assignment = ClaimAssignment(
        classification_attempt_id=attempt.id,
        claim_fingerprint="copper-claim",
        economic_theme_id=child.id,
        exposure_support="direct",
        claim_payload={
            "securities": [
                {
                    "security_id": 42,
                    "role": "producer",
                    "confidence": 0.9,
                    "directness": "direct",
                    "rationale": "Copper producer",
                }
            ],
            "signals": [
                {
                    "signal_kind": "breakout",
                    "security_id": 42,
                    "detected_at": NOW.isoformat(),
                    "effective_at": NOW.isoformat(),
                    "normalized_payload": {"strength": 0.8},
                }
            ],
        },
        provenance={},
    )
    db_session.add(assignment)
    db_session.commit()
    eligibility = db_session.scalar(
        select(LensEligibilityRevision).where(
            LensEligibilityRevision.evidence_packet_id == admitted.packet_id
        )
    )
    return taxonomy, parent, child, admitted, attempt, assignment, eligibility


def _generation(db_session, taxonomy, admitted, attempt, eligibility):
    manifest = GenerationInputManifest(
        status="unsealed",
        semantic_invalidation_revision=0,
        committed_revision_tuples=[],
        selections=[
            {
                "lineage": str(admitted.source_lineage_id),
                "evidence_packet_id": str(admitted.packet_id),
                "eligibility_revision": eligibility.revision_number,
            }
        ],
        created_by="test:publisher",
    )
    db_session.add(manifest)
    db_session.flush()
    manifest.seal(semantic_hash="manifest", artifact_integrity_hash="manifest-artifact")
    interpretation = InterpretationSet(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        created_by="test:publisher",
    )
    db_session.add(interpretation)
    db_session.flush()
    db_session.add(
        InterpretationSelection(
            interpretation_set_id=interpretation.id,
            source_lineage_id=admitted.source_lineage_id,
            evidence_packet_id=admitted.packet_id,
            selected_classification_attempt_id=attempt.id,
            pinned_evidence_revision_ordinal=admitted.evidence_revision_ordinal,
        )
    )
    db_session.flush()
    interpretation.seal(
        semantic_hash="interpretation", artifact_integrity_hash="artifact"
    )
    metrics = MetricsRevision(
        status="unsealed",
        interpretation_set_id=interpretation.id,
        generation_input_manifest_id=manifest.id,
        formula_version="metrics-v1",
        as_of=NOW,
        created_by="test:publisher",
    )
    snapshots = ReaderSnapshotBundle(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        payload={},
        created_by="test:publisher",
    )
    capability = ReaderCapabilityManifest(
        backend_contract=1,
        frontend_contract=1,
        migration_version="0049",
        consumer_test_hash="tests",
        verified_by="test:publisher",
    )
    db_session.add_all([metrics, snapshots, capability])
    db_session.flush()
    metrics.seal(semantic_hash="metrics", artifact_integrity_hash="metrics-artifact")
    snapshots.seal(
        semantic_hash="snapshots", artifact_integrity_hash="snapshot-artifact"
    )
    generation = ServingGeneration(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=interpretation.id,
        metrics_revision_id=metrics.id,
        generation_input_manifest_id=manifest.id,
        reader_snapshot_bundle_id=snapshots.id,
        reader_capability_manifest_id=capability.id,
        semantic_hash="generation",
        artifact_integrity_hash="generation-artifact",
        created_by="test:publisher",
    )
    db_session.add(generation)
    db_session.commit()
    return generation


def test_materializes_primary_parent_constituent_and_signal_facts_idempotently(
    db_session,
):
    taxonomy, parent, _child, admitted, attempt, assignment, eligibility = _setup(
        db_session
    )

    first = materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=eligibility.evidence_channels,
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    second = materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=eligibility.evidence_channels,
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    db_session.commit()

    assert first == second
    assert first.primary_observations == 2
    assert first.derived_observations == 2
    assert first.constituent_exposures == 1
    assert first.signal_observations == 1
    derived = db_session.scalars(
        select(ThemeObservation).where(
            ThemeObservation.observation_kind == "derived_parent"
        )
    ).all()
    assert {row.payload["economic_theme_id"] for row in derived} == {str(parent.id)}
    assert all(
        row.payload["root_claim_id"] == assignment.claim_fingerprint for row in derived
    )
    signal = db_session.scalar(select(ThemeSignalObservation))
    assert signal.payload["source_family_id"] == str(admitted.source_family_id)
    assert signal.payload["effective_at"] == NOW.isoformat()


def test_generation_queries_ignore_later_auxiliary_revisions(db_session):
    taxonomy, _parent, _child, admitted, attempt, _assignment, eligibility = _setup(
        db_session
    )
    materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=eligibility.evidence_channels,
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    generation = _generation(db_session, taxonomy, admitted, attempt, eligibility)
    service = EconomicThemeObservationService(SessionLocal)
    before = service.observations_for_generation(generation.id)
    EconomicSourceAdmissionService(db_session).revise_lens_eligibility(
        admitted.packet_id,
        add="technical",
        reason="later eligibility",
    )
    db_session.commit()

    after = service.observations_for_generation(generation.id)
    constituents = service.constituents_for_generation(generation.id)
    signals = service.signals_for_generation(generation.id)

    assert after == before
    assert {row.evidence_channel for row in after} == {"fundamental", "narrative"}
    assert [(row.security_id, row.exposure_kind) for row in constituents] == [
        (42, "producer")
    ]
    assert signals == []


def test_metrics_exclude_signals_without_pinned_technical_eligibility(db_session):
    taxonomy, _parent, child, admitted, attempt, _assignment, eligibility = _setup(
        db_session
    )
    materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=eligibility.evidence_channels,
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    generation = _generation(db_session, taxonomy, admitted, attempt, eligibility)
    service = EconomicThemeMetricsService(db_session)
    inputs = service._load_inputs(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=generation.interpretation_set_id,
        generation_input_manifest_id=generation.generation_input_manifest_id,
        pinned_eligibility_revisions={},
    )
    selected = next(value for value in inputs if value.theme_id == child.id)

    assert selected.signals == ()
    assert service.calculate(selected, as_of=NOW).technical_attention.availability == (
        "unavailable"
    )


def test_generation_filters_observations_by_pinned_lens_eligibility(db_session):
    taxonomy, _parent, _child, admitted, attempt, _assignment, eligibility = _setup(
        db_session
    )
    materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=eligibility.evidence_channels,
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    revised = EconomicSourceAdmissionService(db_session).revise_lens_eligibility(
        admitted.packet_id,
        remove="fundamental",
        reason="fundamental evidence no longer eligible",
    )
    generation = _generation(db_session, taxonomy, admitted, attempt, revised)

    observations = EconomicThemeObservationService(
        SessionLocal
    ).observations_for_generation(generation.id)

    assert {row.evidence_channel for row in observations} == {"narrative"}


def test_snapshot_filters_observations_by_pinned_lens_eligibility(db_session):
    taxonomy, parent, child, admitted, attempt, _assignment, eligibility = _setup(
        db_session
    )
    materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=eligibility.evidence_channels,
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    revised = EconomicSourceAdmissionService(db_session).revise_lens_eligibility(
        admitted.packet_id,
        remove="fundamental",
        reason="fundamental evidence no longer eligible",
    )
    generation = _generation(db_session, taxonomy, admitted, attempt, revised)

    bundle = build_snapshot_bundle(
        db_session,
        GenerationSnapshotInputs(
            taxonomy_version_id=taxonomy.id,
            interpretation_set_id=generation.interpretation_set_id,
            generation_input_manifest_id=generation.generation_input_manifest_id,
            metrics_revision_id=generation.metrics_revision_id,
            created_by="test:publisher",
        ),
    )
    catalog = db_session.scalar(
        select(ReaderSnapshotEntry).where(
            ReaderSnapshotEntry.reader_snapshot_bundle_id == bundle.id,
            ReaderSnapshotEntry.snapshot_kind == "economic_themes",
        )
    ).payload
    by_id = {row["economic_theme_id"]: row for row in catalog["themes"]}

    assert by_id[str(child.id)]["direct_observation_count"] == 1
    assert by_id[str(parent.id)]["derived_observation_count"] == 1
    assert by_id[str(child.id)]["signals"] == []


def test_direct_root_count_deduplicates_source_family_and_excludes_derived(db_session):
    taxonomy, _parent, child, admitted, attempt, _assignment, eligibility = _setup(
        db_session
    )
    db_session.add(
        ClaimAssignment(
            classification_attempt_id=attempt.id,
            claim_fingerprint="second-claim-same-source",
            economic_theme_id=child.id,
            exposure_support="direct",
            claim_payload={"securities": [], "signals": []},
            provenance={},
        )
    )
    db_session.commit()
    materialize_assignment_facts(
        db_session,
        classification_attempt_id=attempt.id,
        evidence_channels=("narrative",),
        taxonomy_version_id=taxonomy.id,
        detector_policy_version="signals-v1",
    )
    generation = _generation(db_session, taxonomy, admitted, attempt, eligibility)
    service = EconomicThemeObservationService(SessionLocal)

    count = service.direct_root_count(
        generation.id,
        economic_theme_id=child.id,
        evidence_channel="narrative",
        utc_day=date(2026, 9, 21),
    )

    assert count == 1
    assert db_session.scalar(select(func.count()).select_from(ThemeObservation)) == 4
    assert (
        db_session.scalar(select(func.count()).select_from(ThemeConstituentExposure))
        == 1
    )
