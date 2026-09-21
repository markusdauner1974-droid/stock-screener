from __future__ import annotations

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
)
from app.models.economic_taxonomy import EconomicThemeAlias, TaxonomyVersion


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires PostgreSQL row locks and immutable triggers",
)


def _sealed_snapshot():
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    repo = EconomicTaxonomyRepository(session)
    draft = repo.create_draft(actor="test:postgres", reason="trigger contract")
    theme = repo.create_theme(
        draft.id,
        display_name="Copper",
        definition="Copper exposure.",
        mechanism="Copper economics",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
    )
    sealed = repo.seal_draft(draft.id)
    session.commit()
    return factory, sealed.id, theme.id


def test_database_trigger_rejects_direct_mutation_of_sealed_snapshot():
    factory, version_id, _theme_id = _sealed_snapshot()
    session = factory()
    try:
        with pytest.raises(DBAPIError, match="sealed_snapshot_immutable"):
            session.execute(
                update(TaxonomyVersion)
                .where(TaxonomyVersion.id == version_id)
                .values(status="draft")
            )
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_database_trigger_rejects_insert_after_sealing():
    factory, version_id, theme_id = _sealed_snapshot()
    session = factory()
    try:
        with pytest.raises(DBAPIError, match="sealed_snapshot_immutable"):
            session.execute(
                insert(EconomicThemeAlias).values(
                    id="00000000-0000-0000-0000-000000000111",
                    taxonomy_version_id=version_id,
                    theme_id=theme_id,
                    alias="Late alias",
                    normalized_alias="late alias",
                    created_by="test:postgres",
                )
            )
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_version_row_lock_blocks_concurrent_snapshot_mutation():
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    setup = factory()
    repo = EconomicTaxonomyRepository(setup)
    draft = repo.create_draft(actor="test:postgres", reason="lock contract")
    theme = repo.create_theme(
        draft.id,
        display_name="Memory",
        definition="Memory exposure.",
        mechanism="Memory supply and demand",
        lifecycle="provisional",
        lifecycle_policy_version="lifecycle-v1",
    )
    setup.commit()
    setup.close()

    locker = engine.connect()
    contender = engine.connect()
    lock_tx = locker.begin()
    contender_tx = contender.begin()
    try:
        locker.execute(
            select(TaxonomyVersion.id)
            .where(TaxonomyVersion.id == draft.id)
            .with_for_update()
        )
        contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError):
            contender.execute(
                insert(EconomicThemeAlias).values(
                    id="00000000-0000-0000-0000-000000000222",
                    taxonomy_version_id=draft.id,
                    theme_id=theme.id,
                    alias="Blocked alias",
                    normalized_alias="blocked alias",
                    created_by="test:postgres",
                )
            )
    finally:
        contender_tx.rollback()
        lock_tx.rollback()
        contender.close()
        locker.close()
