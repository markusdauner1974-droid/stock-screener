"""#473: the governed V1 seed adopts an implicit legacy authority row."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.economic_taxonomy import TaxonomyVersion
from app.models.economic_taxonomy_runtime import TaxonomyAuthority
from app.services.economic_taxonomy_seed import SeedRefused, seed_governed_snapshot


def _authority(db_session, **overrides):
    # The row lock_authority() inserts on the first fenced legacy write.
    row = TaxonomyAuthority(
        id=1, mode="legacy", processing_head_revision=0, authority_epoch=1,
        writes_fenced=False, semantic_invalidation_revision=0,
        cutover_catch_up_cursor=[], rollback_state="ready",
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    db_session.add(row)
    db_session.commit()
    return row


def _seed_script():
    path = Path(__file__).resolve().parents[2] / "scripts/seed_economic_taxonomy.py"
    spec = importlib.util.spec_from_file_location("seed_economic_taxonomy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runbook_seed_command_prints_the_draft_then_stops(db_session, capsys):
    script = _seed_script()

    assert script.main(["--actor", "operator"]) == 0
    draft_id = capsys.readouterr().out.strip()
    assert script.main(["--actor", "operator"]) == 1

    db_session.expire_all()
    assert str(db_session.get(TaxonomyAuthority, 1).processing_taxonomy_version_id) == draft_id
    assert "STOP:" in capsys.readouterr().err


def _drafts(db_session):
    return db_session.scalar(select(func.count()).select_from(TaxonomyVersion))


def test_seed_creates_the_authority_when_none_exists(db_session):
    draft_id = seed_governed_snapshot(db_session, actor="operator")

    authority = db_session.get(TaxonomyAuthority, 1)
    assert authority.mode == "legacy"
    assert authority.authority_epoch == 1
    assert authority.processing_taxonomy_version_id == draft_id
    assert authority.processing_head_revision == 1


def test_seed_adopts_an_implicit_legacy_row_and_keeps_its_epoch(db_session):
    _authority(db_session, authority_epoch=3)

    draft_id = seed_governed_snapshot(db_session, actor="operator")

    db_session.expire_all()
    authority = db_session.get(TaxonomyAuthority, 1)
    assert authority.processing_taxonomy_version_id == draft_id
    assert authority.authority_epoch == 3
    assert authority.processing_head_revision == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"processing_taxonomy_version_id": "already-seeded"},
        {"mode": "shadow"},
        {"writes_fenced": True},
    ],
    ids=["already-seeded", "not-legacy", "writes-fenced"],
)
def test_seed_refuses_a_row_it_cannot_adopt(db_session, overrides):
    if overrides.get("processing_taxonomy_version_id") == "already-seeded":
        overrides["processing_taxonomy_version_id"] = seed_governed_snapshot(
            db_session, actor="operator"
        )
        drafts = _drafts(db_session)
    else:
        _authority(db_session, **overrides)
        drafts = _drafts(db_session)

    with pytest.raises(SeedRefused):
        seed_governed_snapshot(db_session, actor="operator")

    assert _drafts(db_session) == drafts
