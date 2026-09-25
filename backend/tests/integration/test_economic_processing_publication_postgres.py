from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock

import pytest
from app.database import engine
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy import EconomicTheme
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ExtractionArtifact,
    TaxonomyAuthority,
    TaxonomySourceRevisionLog,
)
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_processor import EconomicTaxonomyProcessor
from app.services.economic_taxonomy_seed import seed_initial_dimensions
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires PostgreSQL writer fencing and row locks",
)

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


class FirstResolutionBarrier:
    def __init__(self, barrier: Barrier):
        self.barrier = barrier
        self._used = False
        self._lock = Lock()

    def after(self, point: str):
        if point != "resolution_complete":
            return
        with self._lock:
            if self._used:
                return
            self._used = True
        self.barrier.wait(timeout=10)


def _candidate(name: str, facets: dict[str, str]):
    return {
        "candidate_key": name.casefold().replace(" ", "-"),
        "display_name": name,
        "raw_facets": facets,
        "mechanism": "Demand changes industry economics.",
        "evidence_spans": [f"{name} demand rose."],
        "relationship_evidence": [],
        "exposure_support": "direct",
        "development_support": "present",
        "candidate_kind": "economic_exposure",
        "securities": [],
        "unknown_dimensions": [],
        "review_reasons": [],
    }


def _setup(*, existing_memory: bool, candidates):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        repo = EconomicTaxonomyRepository(session)
        draft = repo.create_draft(actor="test:postgres", reason="processor race")
        seed_initial_dimensions(repo, draft.id, actor="test:postgres")
        memory = None
        if existing_memory:
            memory = repo.create_theme(
                draft.id,
                display_name="Memory",
                definition="Memory semiconductor exposure.",
                mechanism="Memory supply and demand",
                lifecycle="established",
                lifecycle_policy_version="lifecycle-v1",
                actor="test:postgres",
            )
            repo.assign_facet(
                draft.id,
                memory.id,
                "industry",
                "memory_semiconductors",
                actor="test:postgres",
            )
        sealed = repo.seal_draft(draft.id)
        facet_hash = repo.facet_catalog_semantic_hash(sealed.id)
        session.add(
            TaxonomyAuthority(
                id=1,
                mode="shadow",
                processing_taxonomy_version_id=sealed.id,
                processing_head_revision=10,
                authority_epoch=3,
                writes_fenced=False,
                rollback_state="ready",
            )
        )

    request_ids = []
    with factory.begin() as session:
        for index, candidate in enumerate(candidates):
            admitted = EconomicSourceAdmissionService(session).admit_content(
                EvidenceAdmission(
                    provider="x",
                    canonical_item_id=f"race-post-{index}",
                    capture_route="legacy",
                    original_text=f"{candidate['display_name']} demand rose.",
                    preparation_version="prep-v1",
                    captured_at=NOW,
                    available_at=NOW,
                )
            )
            request = EconomicTaxonomyWorkRepository(session).enqueue_request(
                source_lineage_id=admitted.source_lineage_id,
                evidence_packet_id=admitted.packet_id,
                policy_bundle_version="bundle-v1",
                available_at=NOW,
            )
            extraction = ExtractionArtifact(
                evidence_packet_id=request.evidence_packet_id,
                extraction_policy_version="extract-v1",
                result_status="accepted_candidates",
                result_payload={
                    "status": "accepted_candidates",
                    "candidates": [candidate],
                },
                provider_response_hash=f"extract-{index}",
            )
            session.add(extraction)
            session.flush()
            session.add(
                ClaimReviewArtifact(
                    extraction_artifact_id=extraction.id,
                    claim_review_policy_version="review-v1",
                    facet_catalog_semantic_hash=facet_hash,
                    result_status="accepted_candidates",
                    result_payload={
                        "status": "accepted_candidates",
                        "accepted": [candidate],
                        "held": [],
                    },
                    provider_response_hash=f"review-{index}",
                )
            )
            request_ids.append(request.id)

    leases = []
    with factory() as session:
        work = EconomicTaxonomyWorkRepository(session)
        for index in range(len(request_ids)):
            claimed = work.claim_next(worker_id=f"worker-{index}", now=NOW)
            leases.append((claimed.id, claimed.lease_token))
            session.commit()
    return factory, sealed.id, memory.id if memory else None, leases


def _processor(factory, *, fault=None):
    return EconomicTaxonomyProcessor(
        factory,
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
        lifecycle_policy_version="lifecycle-v1",
        fault_injector=fault,
    )


def test_concurrent_new_identity_race_creates_one_identity_and_truthful_attempts():
    candidate = _candidate("HBM", {"product": "HBM"})
    factory, _head, _memory, leases = _setup(
        existing_memory=False,
        candidates=[candidate, candidate],
    )
    barrier = Barrier(2)

    def process(lease):
        return _processor(factory, fault=FirstResolutionBarrier(barrier)).process(
            *lease
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(process, leases))

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(EconomicTheme)) == 1
        assert session.scalar(select(func.count()).select_from(ClaimAssignment)) == 2
        assert (
            session.scalar(select(func.count()).select_from(ClassificationAttempt)) == 3
        )
        assert (
            session.scalar(select(func.count()).select_from(TaxonomySourceRevisionLog))
            == 2
        )
        assert session.get(TaxonomyAuthority, 1).processing_head_revision == 11
    assert sum(result.created_identity_count for result in results) == 1


def test_concurrent_existing_observations_do_not_advance_processing_head():
    candidate = _candidate("Memory", {"industry": "Memory"})
    factory, original_head, memory_id, leases = _setup(
        existing_memory=True,
        candidates=[candidate, candidate],
    )
    barrier = Barrier(2)

    def process(lease):
        return _processor(factory, fault=FirstResolutionBarrier(barrier)).process(
            *lease
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(process, leases))

    with factory() as session:
        authority = session.get(TaxonomyAuthority, 1)
        assigned = set(session.scalars(select(ClaimAssignment.economic_theme_id)))
        assert authority.processing_taxonomy_version_id == original_head
        assert authority.processing_head_revision == 10
        assert assigned == {memory_id}
        assert (
            session.scalar(select(func.count()).select_from(ClassificationAttempt)) == 2
        )
    assert all(result.output_taxonomy_version_id is None for result in results)
