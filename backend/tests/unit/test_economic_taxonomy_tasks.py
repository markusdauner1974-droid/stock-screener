from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from app.database import SessionLocal
from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
)
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import (
    ProcessingRequest,
    ReaderCapabilityManifest,
    ServingGenerationEvent,
    SourceLineage,
    TaxonomyAuthority,
)
from app.services.economic_exposure_claim_review import ClaimReviewSchemaError
from app.services.economic_exposure_extraction import (
    BudgetExhausted,
    EvidenceSchemaError,
)
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_benchmark_store import (
    register_verified_benchmark,
)
from app.services.economic_taxonomy_publication import (
    CompatibilityProjection,
    EconomicTaxonomyPublicationCoordinator,
)
from app.tasks.economic_taxonomy_tasks import (
    EconomicExtractionReviewPipeline,
    EconomicTaxonomyTaskService,
    _service,
    build_default_economic_taxonomy_pipeline,
    classify_dirty_revisions,
    configure_economic_taxonomy_pipeline,
    refresh_is_coalesced,
)
from sqlalchemy import event, select

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
ADMIN = AdminPrincipal(
    subject="admin:test",
    auth_method="admin_api_key",
    roles=frozenset({"taxonomy:review"}),
)


class _Pipeline:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []

    def process(self, request_id, lease_token):
        self.calls.append((request_id, lease_token))
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(classification_attempt_id=uuid4())


def _authority(db_session, *, mode="shadow"):
    row = TaxonomyAuthority(
        id=1,
        mode=mode,
        processing_head_revision=1,
        authority_epoch=7,
        writes_fenced=False,
        semantic_invalidation_revision=0,
        cutover_catch_up_cursor=[],
        rollback_state="ready",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _published_generation(db_session, *, with_projection: bool):
    repository = EconomicTaxonomyRepository(db_session)
    draft = repository.create_draft(actor=ADMIN.subject, reason="task fixture")
    taxonomy = repository.seal_draft(draft.id)
    capability = ReaderCapabilityManifest(
        backend_contract=1,
        frontend_contract=1,
        migration_version="0055",
        consumer_test_hash=str(uuid4()),
        verified_by=ADMIN.subject,
    )
    authority = TaxonomyAuthority(
        id=1,
        mode="dual",
        processing_taxonomy_version_id=taxonomy.id,
        processing_head_revision=1,
        authority_epoch=7,
        writes_fenced=False,
        semantic_invalidation_revision=0,
        cutover_catch_up_cursor=[],
        rollback_state="ready",
    )
    db_session.add_all([capability, authority])
    register_verified_benchmark(
        db_session,
        report={
            "passed": True,
            "fixture_version": 1,
            "taxonomy_hash": taxonomy.semantic_hash,
            "policy_bundle": "economic-taxonomy-v1",
            "errors": [],
            "cases": [],
        },
        verified_by=ADMIN.subject,
    )
    db_session.commit()

    def compatibility(_session, context):
        if not with_projection:
            return []
        return [
            CompatibilityProjection(
                source_lineage="post:notification-lost",
                projection_kind="legacy_theme",
                projection_version=1,
                target="legacy",
                payload={"themes": ["memory"]},
                origin_representation="economic",
                selected_interpretation_version=str(context.interpretation_set_id),
                mapping_version=str(context.taxonomy_version_id),
            )
        ]

    factory = lambda: db_session.__class__(bind=db_session.get_bind())
    coordinator = EconomicTaxonomyPublicationCoordinator(
        factory,
        compatibility_builder=compatibility,
    )
    cutoff = coordinator.capture_cutoff(principal=ADMIN, selections=[])
    prepared = coordinator.prepare_generation(
        cutoff,
        principal=ADMIN,
        reader_capability_manifest_id=capability.id,
        target_mode="economic",
    )
    coordinator.publish_generation(prepared.id, principal=ADMIN)
    return coordinator, prepared.id, capability.id


class _Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def test_celery_service_constructs_configured_default_pipeline(monkeypatch):
    pipeline = _Pipeline()
    configure_economic_taxonomy_pipeline(None)
    monkeypatch.setattr(
        "app.tasks.economic_taxonomy_tasks.build_default_economic_taxonomy_pipeline",
        lambda _session_factory: pipeline,
    )

    service = _service()

    assert service.pipeline is pipeline


def test_default_pipeline_wires_provider_to_all_processing_stages(
    db_session, monkeypatch
):
    repository = EconomicTaxonomyRepository(db_session)
    taxonomy = repository.seal_draft(
        repository.create_draft(actor=ADMIN.subject, reason="pipeline fixture").id
    )
    authority = _authority(db_session)
    authority.processing_taxonomy_version_id = taxonomy.id
    db_session.commit()
    provider = Mock()
    reservations = Mock()
    monkeypatch.setattr(
        "app.services.economic_taxonomy_llm_provider.build_economic_taxonomy_provider",
        lambda _session_factory: (provider, reservations),
    )

    pipeline = build_default_economic_taxonomy_pipeline(SessionLocal)

    assert isinstance(pipeline, EconomicExtractionReviewPipeline)
    assert pipeline.extractor.provider is provider
    assert pipeline.reviewer.provider is provider
    assert pipeline.extractor.reservations is reservations
    assert pipeline.reviewer.reservations is reservations


def test_legacy_mode_processing_is_noop(db_session):
    _authority(db_session, mode="legacy")
    pipeline = _Pipeline()

    result = EconomicTaxonomyTaskService(
        SessionLocal, pipeline=pipeline, clock=lambda: NOW
    ).process(limit=50, worker_id="worker:test")

    assert result == {"status": "skipped", "reason": "legacy_mode"}
    assert pipeline.calls == []


def test_process_batch_never_exceeds_limit(db_session, monkeypatch):
    _authority(db_session)
    leases = [SimpleNamespace(id=uuid4(), lease_token=uuid4()) for _ in range(20)]
    claimed = []

    def claim_next(_self, **_kwargs):
        if not leases:
            return None
        row = leases.pop(0)
        claimed.append(row)
        return row

    monkeypatch.setattr(
        "app.tasks.economic_taxonomy_tasks.EconomicTaxonomyWorkRepository.claim_next",
        claim_next,
    )
    pipeline = _Pipeline()

    result = EconomicTaxonomyTaskService(
        SessionLocal, pipeline=pipeline, clock=lambda: NOW
    ).process(limit=10, worker_id="worker:test")

    assert result["claimed"] == 10
    assert result["processed"] == 10
    assert len(pipeline.calls) == 10


def test_budget_exhaustion_stops_batch_before_another_provider_call(
    db_session, monkeypatch
):
    _authority(db_session)
    lease = SimpleNamespace(id=uuid4(), lease_token=uuid4())
    claim_count = 0
    retries = []

    def claim_next(_self, **_kwargs):
        nonlocal claim_count
        claim_count += 1
        return lease

    def retry(_self, request_id, _lease_token, *, reason, delay):
        retries.append((request_id, reason, delay))

    monkeypatch.setattr(
        "app.tasks.economic_taxonomy_tasks.EconomicTaxonomyWorkRepository.claim_next",
        claim_next,
    )
    monkeypatch.setattr(
        EconomicTaxonomyTaskService,
        "_retry_request",
        retry,
    )
    pipeline = _Pipeline(failure=BudgetExhausted("budget_exhausted"))

    result = EconomicTaxonomyTaskService(
        SessionLocal, pipeline=pipeline, clock=lambda: NOW
    ).process(limit=10, worker_id="worker:test")

    assert result["claimed"] == 1
    assert result["reason"] == "budget_exhausted"
    assert claim_count == 1
    assert retries == [(lease.id, "budget_exhausted", timedelta(minutes=5))]


@pytest.mark.parametrize(
    "failure",
    (
        EvidenceSchemaError("invalid extraction schema"),
        ClaimReviewSchemaError("invalid review schema"),
    ),
    ids=("extraction", "claim-review"),
)
def test_invalid_provider_schema_terminalizes_processing_request(
    db_session, failure
):
    _authority(db_session)
    admitted = EconomicSourceAdmissionService(db_session).admit_content(
        EvidenceAdmission(
            provider="test",
            canonical_item_id=f"schema-{type(failure).__name__}",
            capture_route="test",
            original_text="Malformed provider response fixture",
            preparation_version="prep-v1",
            available_at=NOW,
            evidence_channels=("narrative",),
        )
    )
    request = EconomicTaxonomyWorkRepository(db_session).enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="economic-taxonomy-v1",
        available_at=NOW,
    )
    request_id = request.id
    db_session.commit()

    result = EconomicTaxonomyTaskService(
        SessionLocal,
        pipeline=_Pipeline(failure=failure),
        clock=lambda: NOW,
    ).process(limit=1, worker_id="worker:schema")

    db_session.expire_all()
    stored = db_session.get(ProcessingRequest, request_id)
    assert result["claimed"] == 1
    assert result["terminal_failures"] == 1
    assert stored.status == "terminal_failure"
    assert stored.lease_token is None
    assert stored.lease_owner is None
    assert stored.lease_expires_at is None


def test_processing_pipeline_runs_extract_review_then_fenced_processor(monkeypatch):
    request_id = uuid4()
    lease_token = uuid4()
    extraction = SimpleNamespace(id=uuid4())
    expected = SimpleNamespace(classification_attempt_id=uuid4())
    extractor = Mock()
    extractor.extract.return_value = extraction
    reviewer = Mock()
    processor = Mock()
    processor.process.return_value = expected
    pipeline = EconomicExtractionReviewPipeline(
        None,
        extractor=extractor,
        reviewer=reviewer,
        processor=processor,
    )
    monkeypatch.setattr(
        pipeline, "_facet_hash_for_request", lambda _request_id: "facet-hash-v1"
    )

    result = pipeline.process(request_id, lease_token)

    assert result is expected
    extractor.extract.assert_called_once_with(request_id)
    reviewer.review.assert_called_once_with(
        extraction,
        request_id=request_id,
        facet_hash="facet-hash-v1",
    )
    processor.process.assert_called_once_with(request_id, lease_token)


def test_dirty_revision_classification_holds_structural_work():
    rows = [
        SimpleNamespace(id=uuid4(), revision_kind="classification_attempt"),
        SimpleNamespace(id=uuid4(), revision_kind="association_revision"),
        SimpleNamespace(id=uuid4(), revision_kind="structural_operation"),
        SimpleNamespace(id=uuid4(), revision_kind="dimension_proposal"),
    ]

    classified = classify_dirty_revisions(rows)

    assert classified.routine_revision_ids == (str(rows[0].id), str(rows[1].id))
    assert classified.held_revision_ids == (
        str(rows[2].id),
        str(rows[3].id),
    )


def test_refresh_coalesces_for_five_minutes():
    assert refresh_is_coalesced(NOW - timedelta(minutes=4), now=NOW)
    assert not refresh_is_coalesced(NOW - timedelta(minutes=5), now=NOW)


def test_limits_are_positive_and_bounded(db_session):
    _authority(db_session)
    service = EconomicTaxonomyTaskService(
        SessionLocal, pipeline=_Pipeline(), clock=lambda: NOW
    )

    with pytest.raises(ValueError, match="limit"):
        service.process(limit=0, worker_id="worker:test")
    with pytest.raises(ValueError, match="limit"):
        service.discover(limit=501)


def test_discovery_limit_applies_only_to_new_requests(db_session):
    _authority(db_session)
    admission = EconomicSourceAdmissionService(db_session)
    admitted = {}
    for index in range(3):
        result = admission.admit_content(
            EvidenceAdmission(
                provider="test",
                canonical_item_id=f"post-{index}",
                capture_route="test",
                original_text=f"Evidence {index}",
                preparation_version="prep-v1",
                available_at=NOW,
                evidence_channels=("narrative",),
            )
        )
        admitted[result.source_lineage_id] = result
    ordered_lineage_ids = db_session.scalars(
        select(SourceLineage.id).order_by(SourceLineage.id)
    ).all()
    work = EconomicTaxonomyWorkRepository(db_session)
    for lineage_id in ordered_lineage_ids[:2]:
        result = admitted[lineage_id]
        work.enqueue_request(
            source_lineage_id=lineage_id,
            evidence_packet_id=result.packet_id,
            policy_bundle_version="economic-taxonomy-v1",
            available_at=NOW,
        )
    db_session.commit()

    discovered = EconomicTaxonomyTaskService(
        SessionLocal, pipeline=_Pipeline(), clock=lambda: NOW
    ).discover(limit=1)

    db_session.expire_all()
    expected = admitted[ordered_lineage_ids[2]]
    assert discovered["discovered"] == 1
    assert discovered["enqueued"] == 1
    assert db_session.scalar(
        select(ProcessingRequest.id).where(
            ProcessingRequest.source_lineage_id == expected.source_lineage_id,
            ProcessingRequest.evidence_packet_id == expected.packet_id,
            ProcessingRequest.policy_bundle_version == "economic-taxonomy-v1",
        )
    ) is not None


def test_discovery_filters_and_limits_candidates_in_one_database_query(db_session):
    _authority(db_session)
    admission = EconomicSourceAdmissionService(db_session)
    for index in range(3):
        admission.admit_content(
            EvidenceAdmission(
                provider="test",
                canonical_item_id=f"bounded-{index}",
                capture_route="test",
                original_text=f"Bounded evidence {index}",
                preparation_version="prep-v1",
                available_at=NOW,
                evidence_channels=("narrative",),
            )
        )
    db_session.commit()
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        EconomicTaxonomyTaskService(
            SessionLocal, pipeline=_Pipeline(), clock=lambda: NOW
        ).discover(limit=1)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    candidate_queries = [
        statement
        for statement in statements
        if "economic_evidence_precedence_revisions" in statement
        and "economic_lens_eligibility_revisions" in statement
        and "economic_processing_requests" in statement
    ]
    assert len(candidate_queries) == 1
    assert " limit " in candidate_queries[0]


def test_delivery_poll_recovers_missing_publish_notification(db_session):
    coordinator, generation_id, _capability_id = _published_generation(
        db_session, with_projection=True
    )

    result = EconomicTaxonomyTaskService(
        SessionLocal, coordinator=coordinator, clock=lambda: NOW
    ).deliver(limit=10, worker_id="worker:poller")

    assert result["claimed_generation_ids"] == [str(generation_id)]
    assert result["checkpointed"] == 1
    assert result["rollback_state"] == "ready"


def test_delivery_poll_ignores_abandoned_generation(db_session):
    _coordinator, _generation_id, capability_id = _published_generation(
        db_session, with_projection=False
    )
    factory = lambda: db_session.__class__(bind=db_session.get_bind())

    def compatibility(_session, context):
        return [
            CompatibilityProjection(
                source_lineage="post:abandoned",
                projection_kind="legacy_theme",
                projection_version=1,
                target="legacy",
                payload={"themes": []},
                origin_representation="economic",
                selected_interpretation_version=str(context.interpretation_set_id),
                mapping_version=str(context.taxonomy_version_id),
            )
        ]

    coordinator = EconomicTaxonomyPublicationCoordinator(
        factory, compatibility_builder=compatibility
    )
    prepared = coordinator.prepare_generation(
        coordinator.capture_cutoff(principal=ADMIN, selections=[]),
        principal=ADMIN,
        reader_capability_manifest_id=capability_id,
        target_mode="economic",
    )
    coordinator.abandon(prepared.id, principal=ADMIN, reason="review required")

    result = EconomicTaxonomyTaskService(
        SessionLocal, coordinator=coordinator, clock=lambda: NOW
    ).deliver(limit=10, worker_id="worker:poller")

    assert str(prepared.id) not in result["claimed_generation_ids"]
    assert result["claimed"] == 0


def test_economic_refresh_publishes_once_then_coalesces(db_session):
    _coordinator, generation_id, _capability_id = _published_generation(
        db_session, with_projection=False
    )
    first_published_at = db_session.scalar(
        select(ServingGenerationEvent.created_at).where(
            ServingGenerationEvent.serving_generation_id == generation_id,
            ServingGenerationEvent.event_type == "published",
        )
    )
    clock = _Clock(first_published_at + timedelta(minutes=6))
    factory = lambda: db_session.__class__(bind=db_session.get_bind())
    coordinator = EconomicTaxonomyPublicationCoordinator(factory, clock=clock)
    authority = db_session.get(TaxonomyAuthority, 1)
    EconomicTaxonomyPublicationRepository(db_session).append_source_revision(
        producer_kind="economic_taxonomy",
        logical_source_key="classification:one",
        revision_kind="classification_attempt",
        revision_number=1,
        content_hash="one",
        authority_epoch=authority.authority_epoch,
    )
    db_session.commit()
    service = EconomicTaxonomyTaskService(
        SessionLocal, coordinator=coordinator, clock=clock
    )

    published = service.refresh()

    assert published["status"] == "published"
    new_generation_id = published["generation_id"]
    second_published_at = db_session.scalar(
        select(ServingGenerationEvent.created_at).where(
            ServingGenerationEvent.serving_generation_id == UUID(new_generation_id),
            ServingGenerationEvent.event_type == "published",
        )
    )
    clock.value = second_published_at + timedelta(minutes=4)
    authority = db_session.get(TaxonomyAuthority, 1)
    EconomicTaxonomyPublicationRepository(db_session).append_source_revision(
        producer_kind="economic_taxonomy",
        logical_source_key="classification:two",
        revision_kind="classification_attempt",
        revision_number=1,
        content_hash="two",
        authority_epoch=authority.authority_epoch,
    )
    db_session.commit()

    coalesced = service.refresh()

    assert coalesced["status"] == "skipped"
    assert coalesced["reason"] == "coalesced"
    assert coalesced["dirty_revision_count"] == 1


def test_refresh_holds_review_required_structural_change(db_session):
    coordinator, _generation_id, _capability_id = _published_generation(
        db_session, with_projection=False
    )
    authority = db_session.get(TaxonomyAuthority, 1)
    revision = EconomicTaxonomyPublicationRepository(db_session).append_source_revision(
        producer_kind="economic_taxonomy",
        logical_source_key="operation:split",
        revision_kind="structural_operation",
        revision_number=1,
        content_hash="split",
        authority_epoch=authority.authority_epoch,
    )
    db_session.commit()

    result = EconomicTaxonomyTaskService(
        SessionLocal, coordinator=coordinator, clock=lambda: NOW
    ).refresh()

    assert result["status"] == "held"
    assert result["held_revision_ids"] == [str(revision.id)]


def test_refresh_rechecks_revisions_committed_while_capturing_cutoff(db_session):
    coordinator, generation_id, _capability_id = _published_generation(
        db_session, with_projection=False
    )
    published_at = db_session.scalar(
        select(ServingGenerationEvent.created_at).where(
            ServingGenerationEvent.serving_generation_id == generation_id,
            ServingGenerationEvent.event_type == "published",
        )
    )
    clock = _Clock(published_at + timedelta(minutes=6))
    authority = db_session.get(TaxonomyAuthority, 1)
    EconomicTaxonomyPublicationRepository(db_session).append_source_revision(
        producer_kind="economic_taxonomy",
        logical_source_key="classification:routine",
        revision_kind="classification_attempt",
        revision_number=1,
        content_hash="routine",
        authority_epoch=authority.authority_epoch,
    )
    db_session.commit()
    original_capture = coordinator.capture_cutoff
    raced_revision_id = None

    def capture_with_raced_structural_revision(*, principal):
        nonlocal raced_revision_id
        with SessionLocal.begin() as session:
            current = session.get(TaxonomyAuthority, 1)
            raced = EconomicTaxonomyPublicationRepository(
                session
            ).append_source_revision(
                producer_kind="economic_taxonomy",
                logical_source_key="operation:raced-split",
                revision_kind="structural_operation",
                revision_number=1,
                content_hash="raced-split",
                authority_epoch=current.authority_epoch,
            )
            raced_revision_id = raced.id
        return original_capture(principal=principal)

    coordinator.capture_cutoff = capture_with_raced_structural_revision

    result = EconomicTaxonomyTaskService(
        SessionLocal, coordinator=coordinator, clock=clock
    ).refresh()

    assert result["status"] == "held"
    assert result["held_revision_ids"] == [str(raced_revision_id)]
