from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
)
from app.models.economic_taxonomy import ECONOMIC_TAXONOMY_TABLES
from app.services.economic_taxonomy_seed import (
    INITIAL_DIMENSIONS,
    normalize_facet,
    seed_initial_dimensions,
)


def _repository():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=ECONOMIC_TAXONOMY_TABLES)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return engine, session, EconomicTaxonomyRepository(session)


def test_initial_dimensions_are_the_exact_v1_catalog():
    assert tuple(INITIAL_DIMENSIONS) == (
        "industry",
        "technology",
        "product",
        "commodity",
        "end_market",
        "customer",
        "supply_chain",
        "geography",
        "policy",
        "regulation",
        "macro",
        "infrastructure",
    )


def test_seed_initial_dimensions_and_canonical_values():
    engine, session, repo = _repository()
    try:
        draft = repo.create_draft(actor="test:admin", reason="seed")
        seed_initial_dimensions(repo, draft.id, actor="test:admin")
        snapshot = repo.load_snapshot(draft.id)

        assert {row["key"] for row in snapshot["dimensions"]} == set(
            INITIAL_DIMENSIONS
        )
        values = {
            (row["dimension_key"], row["normalized_value"])
            for row in snapshot["facet_values"]
        }
        assert {
            ("end_market", "artificial_intelligence"),
            ("industry", "memory_semiconductors"),
            ("product", "hbm"),
            ("technology", "artificial_intelligence"),
        }.issubset(values)
    finally:
        session.close()
        engine.dispose()


def test_normalization_preserves_economic_dimension_semantics():
    assert normalize_facet("end_market", "AI") == "artificial_intelligence"
    assert normalize_facet("industry", "Memory") == "memory_semiconductors"
    assert normalize_facet("product", "High Bandwidth Memory") == "hbm"
    assert normalize_facet("technology", "AI") == "artificial_intelligence"
    assert normalize_facet("commodity", "Copper Cathode") == "copper_cathode"

