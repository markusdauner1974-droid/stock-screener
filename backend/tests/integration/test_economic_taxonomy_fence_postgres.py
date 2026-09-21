from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.models.economic_taxonomy_runtime import TaxonomyAuthority
from app.services.economic_taxonomy_fence import (
    StaleAuthorityEpoch,
    exclusive_publication,
    producer_write,
)

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires PostgreSQL transaction advisory locks",
)


@pytest.fixture
def factory():
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(
        TaxonomyAuthority(
            id=1,
            mode="dual",
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    session.commit()
    session.close()
    return factory


def test_exclusive_switch_waits_for_old_writer_and_fences_stale_epoch(factory):
    writer_entered = Event()
    release_writer = Event()
    publisher_entered = Event()

    def old_writer():
        session = factory()
        try:
            with producer_write(session, expected_epoch=7, allowed_modes={"dual"}):
                writer_entered.set()
                release_writer.wait(timeout=5)
            session.commit()
        finally:
            session.close()

    def publisher():
        session = factory()
        try:
            with exclusive_publication(session) as authority:
                publisher_entered.set()
                authority.authority_epoch = 8
            session.commit()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer_future = pool.submit(old_writer)
        assert writer_entered.wait(timeout=5)
        publisher_future = pool.submit(publisher)
        assert not publisher_entered.wait(timeout=0.2)
        release_writer.set()
        writer_future.result(timeout=5)
        publisher_future.result(timeout=5)

    stale = factory()
    try:
        with pytest.raises(StaleAuthorityEpoch), producer_write(
            stale, expected_epoch=7, allowed_modes={"dual"}
        ):
            pass
    finally:
        stale.rollback()
        stale.close()


def test_manifest_cutoff_includes_late_lower_id_and_ignores_later_ordinary_work(factory):
    first = factory()
    second = factory()
    try:
        repo1 = EconomicTaxonomyPublicationRepository(first)
        repo2 = EconomicTaxonomyPublicationRepository(second)
        # Allocate the first identity before the second transaction commits.
        lower_id = UUID("00000000-0000-0000-0000-000000000001")
        with producer_write(second, expected_epoch=7, allowed_modes={"dual"}):
            repo2.append_source_revision(
                revision_id=UUID("00000000-0000-0000-0000-000000000002"),
                producer_kind="social",
                logical_source_key="post-2",
                revision_kind="decision",
                revision_number=1,
                content_hash="hash-2",
                authority_epoch=7,
            )
        second.commit()
        with producer_write(first, expected_epoch=7, allowed_modes={"dual"}):
            repo1.append_source_revision(
                revision_id=lower_id,
                producer_kind="content",
                logical_source_key="post-1",
                revision_kind="evidence",
                revision_number=1,
                content_hash="hash-1",
                authority_epoch=7,
            )
        first.commit()

        capture = factory()
        try:
            with exclusive_publication(capture):
                manifest = EconomicTaxonomyPublicationRepository(capture).capture_manifest(
                    actor="operator:alice", selections=[]
                )
            capture.commit()
            manifest_id = manifest.id
        finally:
            capture.close()

        later = factory()
        try:
            with producer_write(later, expected_epoch=7, allowed_modes={"dual"}):
                EconomicTaxonomyPublicationRepository(later).append_source_revision(
                    revision_id=uuid4(),
                    producer_kind="content",
                    logical_source_key="post-3",
                    revision_kind="evidence",
                    revision_number=1,
                    content_hash="hash-3",
                    authority_epoch=7,
                )
            later.commit()
        finally:
            later.close()

        check = factory()
        try:
            repo = EconomicTaxonomyPublicationRepository(check)
            frozen = repo.get_manifest(manifest_id)
            assert len(frozen.committed_revision_tuples) == 2
            assert repo.validate_manifest(frozen).valid is True
            repo.append_semantic_invalidation(reason="reviewed split", actor="operator:alice")
            check.commit()
            assert repo.validate_manifest(frozen).valid is False
        finally:
            check.close()
    finally:
        first.close()
        second.close()
