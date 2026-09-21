from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.economic_taxonomy import ECONOMIC_TAXONOMY_TABLES, EconomicTheme
from app.models.economic_taxonomy_runtime import (
    ECONOMIC_TAXONOMY_RUNTIME_TABLES,
    ClaimAssignment,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    EconomicThemeEmbedding,
    EvidencePacket,
    ExtractionArtifact,
    ImmutableRuntimePayload,
    InterpretationSelection,
    InterpretationSet,
    LensEligibilityRevision,
    MetricsRevision,
    ProcessingRequest,
    SocialAssociationRevisionRef,
    SourceFamily,
    SourceLineage,
    ThemeMetric,
    ThemeObservation,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[*ECONOMIC_TAXONOMY_TABLES, *ECONOMIC_TAXONOMY_RUNTIME_TABLES],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source_graph(db):
    family = SourceFamily(
        provider="x",
        canonical_source_key="x:post:42",
        canonical_item_id="42",
    )
    db.add(family)
    db.flush()
    lineage = SourceLineage(source_family_id=family.id)
    db.add(lineage)
    db.flush()
    packet = EvidencePacket(
        source_lineage_id=lineage.id,
        packet_hash="packet-1",
        evidence_content_fingerprint="content-1",
        capture_route="legacy",
        captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        original_text_ref="sha256:original",
        attachment_hashes=[],
        extracted_text_hashes=[],
        grounding_snapshot={},
        preparation_version="prep-v1",
        source_metadata={},
        available_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        precedence_state="effective",
    )
    db.add(packet)
    db.flush()
    request = ProcessingRequest(
        source_lineage_id=lineage.id,
        evidence_packet_id=packet.id,
        policy_bundle_version="policy-v1",
    )
    db.add(request)
    db.flush()
    extraction = ExtractionArtifact(
        evidence_packet_id=packet.id,
        extraction_policy_version="extract-v1",
        result_status="accepted_candidates",
        result_payload={"candidates": [{"name": "Memory"}]},
        provider_response_hash="response-1",
    )
    db.add(extraction)
    db.flush()
    review = ClaimReviewArtifact(
        extraction_artifact_id=extraction.id,
        claim_review_policy_version="review-v1",
        facet_catalog_semantic_hash="facets-v1",
        result_status="accepted_candidates",
        result_payload={"accepted": [{"name": "Memory"}]},
        provider_response_hash="review-response-1",
    )
    db.add(review)
    db.flush()
    return family, lineage, packet, request, extraction, review


def _taxonomy_version(db, label):
    from app.models.economic_taxonomy import TaxonomyVersion

    version = TaxonomyVersion(
        status="draft", created_by="test:author", reason=label
    )
    db.add(version)
    db.flush()
    return version


def _attempt(db, request, review, input_taxonomy, *, status="completed"):
    attempt = ClassificationAttempt(
        processing_request_id=request.id,
        claim_review_artifact_id=review.id,
        input_taxonomy_version_id=input_taxonomy.id,
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
        result_status=status,
        result_payload={"assignments": []},
    )
    db.add(attempt)
    db.flush()
    return attempt


def test_same_request_can_store_attempts_for_actual_h10_and_h11(db):
    _family, _lineage, _packet, request, _extraction, review = _source_graph(db)
    h10 = _taxonomy_version(db, "H10")
    h11 = _taxonomy_version(db, "H11")

    first = _attempt(db, request, review, h10)
    second = _attempt(db, request, review, h11)

    assert first.id != second.id
    assert first.claim_review_artifact_id == second.claim_review_artifact_id


def test_evidence_ordinal_is_monotonic_inside_lineage(db):
    _family, lineage, _packet, _request, _extraction, _review = _source_graph(db)
    packets = [
        EvidencePacket(
            source_lineage_id=lineage.id,
            packet_hash=f"packet-{number}",
            evidence_content_fingerprint=f"content-{number}",
            capture_route="social",
            captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
            original_text_ref=f"sha256:{number}",
            attachment_hashes=[],
            extracted_text_hashes=[],
            grounding_snapshot={},
            preparation_version="prep-v1",
            source_metadata={},
            available_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
            precedence_state="hold_review",
        )
        for number in (2, 3)
    ]
    db.add_all(packets)
    db.flush()

    assert [packet.evidence_revision_ordinal for packet in packets] == [2, 3]


def test_processing_request_identity_excludes_taxonomy_head(db):
    _family, _lineage, packet, request, _extraction, _review = _source_graph(db)
    duplicate = ProcessingRequest(
        source_lineage_id=request.source_lineage_id,
        evidence_packet_id=packet.id,
        policy_bundle_version="policy-v1",
    )
    db.add(duplicate)

    with pytest.raises(IntegrityError):
        db.flush()


def test_artifact_keys_are_exact_and_unique(db):
    _family, _lineage, packet, _request, extraction, review = _source_graph(db)
    db.add(
        ExtractionArtifact(
            evidence_packet_id=packet.id,
            extraction_policy_version="extract-v1",
            result_status="successful_empty",
            result_payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    assert extraction.id is not None
    assert review.facet_catalog_semantic_hash == "facets-v1"


def test_completed_empty_attempt_requires_no_assignment(db):
    _family, _lineage, _packet, request, _extraction, review = _source_graph(db)
    version = _taxonomy_version(db, "empty")
    attempt = _attempt(db, request, review, version)

    assert attempt.result_status == "completed"
    assert attempt.assignments == []


def test_attempt_payload_and_events_are_append_only(db):
    _family, _lineage, _packet, request, _extraction, review = _source_graph(db)
    attempt = _attempt(db, request, review, _taxonomy_version(db, "H10"))
    attempt_id = attempt.id
    db.commit()
    attempt.result_payload = {"assignments": ["changed"]}

    with pytest.raises(ImmutableRuntimePayload, match="runtime_payload_immutable"):
        db.flush()
    db.rollback()

    event_row = ClassificationAttemptEvent(
        classification_attempt_id=attempt_id,
        sequence_number=1,
        event_type="completed",
    )
    db.add(event_row)
    db.flush()
    event_row.event_type = "failed"
    with pytest.raises(ImmutableRuntimePayload, match="runtime_payload_immutable"):
        db.flush()


def test_observation_identity_comes_from_assignment(db):
    _family, _lineage, _packet, request, _extraction, review = _source_graph(db)
    attempt = _attempt(db, request, review, _taxonomy_version(db, "H10"))
    theme = EconomicTheme(created_by="test:author")
    db.add(theme)
    db.flush()
    assignment = ClaimAssignment(
        classification_attempt_id=attempt.id,
        claim_fingerprint="claim-1",
        economic_theme_id=theme.id,
        exposure_support="direct",
        claim_payload={"quote": "Memory demand increased."},
        provenance={"source": "packet-1"},
    )
    db.add(assignment)
    db.flush()
    observation = ThemeObservation(
        claim_assignment_id=assignment.id,
        observation_kind="primary",
        evidence_channel="fundamental",
        derivation_policy_version="derive-v1",
        available_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    db.add(observation)
    db.flush()

    assert observation.claim_assignment_id == assignment.id
    db.add(
        ThemeObservation(
            claim_assignment_id=assignment.id,
            observation_kind="primary",
            evidence_channel="fundamental",
            derivation_policy_version="derive-v1",
            available_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_interpretation_set_seals_once_and_blocks_payload_changes(db):
    _family, lineage, packet, request, _extraction, review = _source_graph(db)
    attempt = _attempt(db, request, review, _taxonomy_version(db, "H10"))
    interpretation = InterpretationSet(status="unsealed", created_by="test:builder")
    db.add(interpretation)
    db.flush()
    selection = InterpretationSelection(
        interpretation_set_id=interpretation.id,
        source_lineage_id=lineage.id,
        evidence_packet_id=packet.id,
        selected_classification_attempt_id=attempt.id,
        pinned_evidence_revision_ordinal=packet.evidence_revision_ordinal,
    )
    db.add(selection)
    db.flush()

    interpretation.seal(
        semantic_hash="semantic-1", artifact_integrity_hash="artifact-1"
    )
    db.flush()
    interpretation.status = "unsealed"
    with pytest.raises(ImmutableRuntimePayload, match="sealed_payload_immutable"):
        db.flush()


def test_sealed_interpretation_rejects_new_selection(db):
    _family, lineage, packet, request, _extraction, review = _source_graph(db)
    attempt = _attempt(db, request, review, _taxonomy_version(db, "H10"))
    interpretation = InterpretationSet(status="unsealed", created_by="test:builder")
    db.add(interpretation)
    db.flush()
    interpretation.seal(
        semantic_hash="semantic-1", artifact_integrity_hash="artifact-1"
    )
    db.flush()
    db.add(
        InterpretationSelection(
            interpretation_set_id=interpretation.id,
            source_lineage_id=lineage.id,
            evidence_packet_id=packet.id,
            selected_classification_attempt_id=attempt.id,
            pinned_evidence_revision_ordinal=packet.evidence_revision_ordinal,
        )
    )

    with pytest.raises(ImmutableRuntimePayload, match="sealed_payload_immutable"):
        db.flush()


def test_metrics_revision_seals_once_and_blocks_metric_changes(db):
    interpretation = InterpretationSet(status="unsealed", created_by="test:builder")
    db.add(interpretation)
    db.flush()
    metrics = MetricsRevision(
        status="unsealed",
        interpretation_set_id=interpretation.id,
        formula_version="metrics-v1",
        as_of=datetime(2026, 9, 21, tzinfo=timezone.utc),
        created_by="test:builder",
    )
    theme = EconomicTheme(created_by="test:author")
    db.add_all([metrics, theme])
    db.flush()
    metric = ThemeMetric(
        metrics_revision_id=metrics.id,
        economic_theme_id=theme.id,
        ranking_view="fundamental_attention",
        available=True,
        raw_value=1.0,
        percentile=100.0,
        components={},
    )
    db.add(metric)
    db.flush()
    metrics.seal(semantic_hash="semantic-1", artifact_integrity_hash="artifact-1")
    db.flush()
    metric.raw_value = 2.0

    with pytest.raises(ImmutableRuntimePayload, match="runtime_payload_immutable"):
        db.flush()


def test_generation_input_uses_social_association_revision_not_pair_only(db):
    first = SocialAssociationRevisionRef(
        association_id=uuid4(), revision_number=1
    )
    second = SocialAssociationRevisionRef(
        association_id=first.association_id, revision_number=2
    )
    db.add_all([first, second])
    db.flush()

    assert first.association_id == second.association_id
    assert first.id != second.id


def test_lens_eligibility_is_append_only_revision_history(db):
    _family, lineage, packet, _request, _extraction, _review = _source_graph(db)
    first = LensEligibilityRevision(
        source_lineage_id=lineage.id,
        evidence_packet_id=packet.id,
        revision_number=1,
        evidence_channels=["technical"],
        reason="initial",
    )
    second = LensEligibilityRevision(
        source_lineage_id=lineage.id,
        evidence_packet_id=packet.id,
        revision_number=2,
        evidence_channels=["technical", "fundamental"],
        reason="lens only",
    )
    db.add_all([first, second])
    db.flush()

    assert first.evidence_channels == ["technical"]
    assert second.evidence_channels == ["technical", "fundamental"]


def test_embedding_cache_key_includes_taxonomy_and_model_inputs(db):
    theme = EconomicTheme(created_by="test:author")
    db.add(theme)
    db.flush()
    first = EconomicThemeEmbedding(
        economic_theme_id=theme.id,
        taxonomy_semantic_hash="taxonomy-1",
        source_text_hash="text-1",
        embedding_model="model",
        model_version="v1",
        embedding=[0.1, 0.2],
    )
    second = EconomicThemeEmbedding(
        economic_theme_id=theme.id,
        taxonomy_semantic_hash="taxonomy-2",
        source_text_hash="text-1",
        embedding_model="model",
        model_version="v1",
        embedding=[0.1, 0.2],
    )
    db.add_all([first, second])
    db.flush()

    assert first.id != second.id
