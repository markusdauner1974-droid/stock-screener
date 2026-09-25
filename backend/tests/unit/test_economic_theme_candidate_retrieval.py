from __future__ import annotations

from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.models.economic_taxonomy_runtime import EconomicThemeEmbedding
from app.services.economic_taxonomy_seed import seed_initial_dimensions
from app.services.economic_theme_candidate_retrieval import retrieve_candidates
from app.services.economic_theme_embedding_service import get_or_recompute_embedding
from sqlalchemy import func, select


class EmbeddingProvider:
    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.calls = 0

    def embed(self, *, text: str, model: str, model_version: str):
        self.calls += 1
        if self.fails:
            raise RuntimeError("provider unavailable")
        return [float(len(text)), 1.0]


def _snapshot(db_session, *, theme_count: int = 1):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:author", reason="retrieval fixture")
    seed_initial_dimensions(repo, draft.id, actor="test:author")
    themes = []
    for index in range(theme_count):
        name = "Memory" if index == 0 else f"Memory Theme {index:02d}"
        theme = repo.create_theme(
            draft.id,
            display_name=name,
            definition=f"{name} economic exposure.",
            mechanism="Memory supply and demand",
            lifecycle="established",
            lifecycle_policy_version="lifecycle-v1",
            actor="test:author",
        )
        repo.add_alias(draft.id, theme.id, f"DRAM {index}", actor="test:author")
        repo.assign_facet(
            draft.id,
            theme.id,
            "industry",
            "memory_semiconductors",
            actor="test:author",
        )
        themes.append(theme)
    sealed = repo.seal_draft(draft.id)
    db_session.commit()
    return sealed, themes


def test_retrieval_is_bounded_and_includes_alias_and_facet_matches(db_session):
    version, themes = _snapshot(db_session, theme_count=25)

    results = retrieve_candidates(
        db_session,
        taxonomy_version_id=version.id,
        proposed={
            "display_name": "DRAM memory",
            "normalized_facets": {"industry": "memory_semiconductors"},
        },
    )

    assert len(results) == 20
    assert themes[0].id in {row.theme_id for row in results}
    assert all(row.retrieval_reasons for row in results)


def test_embedding_cache_uses_exact_sealed_revision_key(db_session):
    version, themes = _snapshot(db_session)
    provider = EmbeddingProvider()

    first = get_or_recompute_embedding(
        db_session,
        taxonomy_version_id=version.id,
        theme_id=themes[0].id,
        embedding_model="embed-small",
        model_version="2026-09",
        provider=provider,
    )
    second = get_or_recompute_embedding(
        db_session,
        taxonomy_version_id=version.id,
        theme_id=themes[0].id,
        embedding_model="embed-small",
        model_version="2026-09",
        provider=provider,
    )

    assert first.id == second.id
    assert provider.calls == 1
    assert (
        db_session.scalar(select(func.count()).select_from(EconomicThemeEmbedding)) == 1
    )


def test_embedding_failure_leaves_lexical_retrieval_available(db_session):
    version, themes = _snapshot(db_session)
    provider = EmbeddingProvider(fails=True)

    embedding = get_or_recompute_embedding(
        db_session,
        taxonomy_version_id=version.id,
        theme_id=themes[0].id,
        embedding_model="embed-small",
        model_version="2026-09",
        provider=provider,
    )
    results = retrieve_candidates(
        db_session,
        taxonomy_version_id=version.id,
        proposed={"display_name": "Memory", "normalized_facets": {}},
    )

    assert embedding is None
    assert results[0].theme_id == themes[0].id
    assert (
        db_session.scalar(select(func.count()).select_from(EconomicThemeEmbedding)) == 0
    )
