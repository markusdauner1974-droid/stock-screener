from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.models.economic_taxonomy_runtime import TaxonomyAuthority
from app.services.economic_taxonomy_fence import (
    StaleAuthorityEpoch,
    exclusive_publication,
)
from app.services.economic_taxonomy_runtime import EconomicTaxonomyRuntimeService

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="requires PostgreSQL locking"
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def test_postgres_checkpoint_compare_and_set_rejects_late_old_revision(db_session):
    service = EconomicTaxonomyRuntimeService(db_session)
    service.apply_replacement(
        target="legacy",
        source_lineage="post:1",
        projection_kind="legacy_theme",
        projection_revision=2,
        payload={"themes": ["new"]},
        origin_representation="economic",
    )
    db_session.commit()

    assert (
        service.apply_replacement(
            target="legacy",
            source_lineage="post:1",
            projection_kind="legacy_theme",
            projection_revision=1,
            payload={"themes": ["old"]},
            origin_representation="economic",
        )
        is False
    )


def test_legacy_writer_cannot_commit_after_epoch_switch(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="dual",
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    writer_entered = Event()
    release_writer = Event()

    def old_writer():
        session = factory()
        try:
            with EconomicTaxonomyRuntimeService(session).legacy_producer_write(
                expected_epoch=7,
                logical_source_key="legacy:old",
                revision_kind="legacy_theme_update",
                content_hash="old",
                auto_commit=True,
            ):
                writer_entered.set()
                release_writer.wait(timeout=5)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(old_writer)
        assert writer_entered.wait(timeout=5)

        def switch():
            session = factory()
            try:
                with exclusive_publication(session) as authority:
                    authority.mode = "economic"
                    authority.authority_epoch = 8
                session.commit()
            finally:
                session.close()

        publisher = pool.submit(switch)
        release_writer.set()
        writer.result(timeout=5)
        publisher.result(timeout=5)

    stale = factory()
    try:
        with (
            pytest.raises(StaleAuthorityEpoch),
            EconomicTaxonomyRuntimeService(stale).legacy_producer_write(
                expected_epoch=7,
                logical_source_key="legacy:late",
                revision_kind="legacy_theme_update",
                content_hash="late",
                auto_commit=True,
            ),
        ):
            pass
    finally:
        stale.rollback()
        stale.close()
