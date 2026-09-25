from __future__ import annotations

from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.services.economic_taxonomy_seed import seed_initial_dimensions
from app.services.economic_theme_candidate_retrieval import retrieve_candidates


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


