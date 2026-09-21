from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.infra.db.models.social_analysis import EconomicSocialAssociation
from app.models.economic_taxonomy import EconomicTheme
from app.models.stock_universe import StockUniverse
from app.services.social_theme_projection_service import EconomicSocialTaxonomyAdapter

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
