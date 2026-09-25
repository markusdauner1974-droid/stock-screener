from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from app.database import engine
from app.infra.db.models.social_analysis import (
    EconomicSocialAssociation,
    EconomicSocialAssociationRevision,
)
from app.models.economic_taxonomy import EconomicTheme
from app.models.stock_universe import StockUniverse
from app.services.economic_social_taxonomy_adapter import EconomicSocialTaxonomyAdapter
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="requires PostgreSQL uniqueness"
)


def test_concurrent_global_pair_creation_converges_on_one_identity(db_session):
    theme = EconomicTheme(created_by="test:social")
    security = StockUniverse(symbol="MU", market="US", is_active=True)
    db_session.add_all([theme, security])
    db_session.commit()
    theme_id = theme.id
    security_id = security.id
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def create():
        with factory() as session:
            association = EconomicSocialTaxonomyAdapter(
                session
            ).get_or_create_association(theme_id, security_id)
            session.commit()
            return association.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(lambda _index: create(), range(2)))

    db_session.expire_all()
    assert len(set(identities)) == 1
    assert db_session.query(EconomicSocialAssociation).count() == 1


def test_two_immutable_revisions_coexist_for_one_global_pair(db_session):
    theme = EconomicTheme(created_by="test:social")
    security = StockUniverse(symbol="MU", market="US", is_active=True)
    db_session.add_all([theme, security])
    db_session.flush()
    adapter = EconomicSocialTaxonomyAdapter(db_session)
    association = adapter.get_or_create_association(theme.id, security.id)

    accepted = adapter.revise(
        association.id,
        state="accepted",
        idempotency_key="pg-social-accepted",
        actor="admin:test",
        reason="reviewed",
        mirror_acknowledged=True,
    )
    rejected = adapter.revise(
        association.id,
        state="rejected",
        idempotency_key="pg-social-rejected",
        actor="admin:test",
        reason="corrected",
        mirror_acknowledged=True,
    )
    db_session.commit()

    revisions = db_session.query(EconomicSocialAssociationRevision).order_by(
        EconomicSocialAssociationRevision.revision_number
    ).all()
    assert [row.id for row in revisions] == [accepted.id, rejected.id]
    assert [row.revision_number for row in revisions] == [1, 2]
    assert [row.state for row in revisions] == ["accepted", "rejected"]
    assert db_session.query(EconomicSocialAssociation).count() == 1
