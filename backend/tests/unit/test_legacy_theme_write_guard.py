"""#472: unfenced legacy Theme writers skip, 409 or refuse under economic authority."""

from __future__ import annotations

import sys

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError

from app.database import get_db
from app.main import app
from app.models.economic_taxonomy_runtime import TaxonomyAuthority
from app.models.theme import ThemeCluster
from app.services import theme_content_recovery_service as recovery
from app.services.legacy_theme_write_guard import (
    ECONOMIC_AUTHORITY_SKIP_REASON,
    LEGACY_WRITE_MODES,
    LegacyThemeWritesBlocked,
    mark_legacy_theme_writer,
    skip_in_economic_authority,
)
from app.tasks import (
    live_attachment_tasks,
    theme_discovery_tasks,
    theme_intelligence_tasks,
)


def _authority(db_session, mode):
    db_session.add(TaxonomyAuthority(
        id=1, mode=mode, processing_head_revision=1, authority_epoch=1,
        writes_fenced=False, semantic_invalidation_revision=0,
        cutover_catch_up_cursor=[], rollback_state="ready",
    ))
    db_session.add(ThemeCluster(
        canonical_key="ai_memory", display_name="AI Memory", name="AI Memory",
        pipeline="technical",
    ))
    db_session.commit()


def _clusters(db_session):
    return db_session.scalar(select(func.count()).select_from(ThemeCluster))


GUARDED_TASKS = [
    (theme_discovery_tasks.extract_themes, ()),
    (theme_discovery_tasks.reprocess_failed_themes, ()),
    (theme_discovery_tasks.calculate_theme_metrics, ()),
    (theme_discovery_tasks.recompute_stale_theme_embeddings, ()),
    (theme_discovery_tasks.promote_candidate_themes, ()),
    (theme_discovery_tasks.apply_lifecycle_policies, ()),
    (theme_discovery_tasks.infer_theme_relationships, ()),
    (theme_discovery_tasks.validate_themes, ()),
    (theme_discovery_tasks.check_alerts, ()),
    (theme_discovery_tasks.run_full_pipeline, ()),
    (theme_discovery_tasks.consolidate_themes, ()),
    (theme_discovery_tasks.compute_l1_metrics, ()),
    (theme_discovery_tasks.run_taxonomy_assignment, ()),
    (theme_discovery_tasks.recompute_l1_centroid_embeddings, ()),
    (live_attachment_tasks.refresh_attachment_themes, ([],)),
    (theme_intelligence_tasks.refresh_groups, ()),
]


@pytest.mark.parametrize("task,args", GUARDED_TASKS, ids=[t.name.rsplit(".", 1)[-1] for t, _ in GUARDED_TASKS])
def test_task_skips_with_a_reason_under_economic_authority(db_session, task, args):
    _authority(db_session, "economic")
    before = _clusters(db_session)

    result = task(*args)

    assert result["status"] == "skipped"
    assert result["reason"] == ECONOMIC_AUTHORITY_SKIP_REASON
    assert _clusters(db_session) == before


def _switch_to_economic():
    from app.database import SessionLocal

    with SessionLocal() as other:
        other.get(TaxonomyAuthority, 1).mode = "economic"
        other.commit()


def test_task_write_after_a_mid_run_cutover_fails_closed(db_session):
    # The entry check passes in legacy mode; cutover happens before the body
    # commits, so its first write re-checks under the fence and is refused.
    _authority(db_session, "legacy")
    from app.database import SessionLocal

    @skip_in_economic_authority
    def body():
        _switch_to_economic()
        with SessionLocal() as session:
            session.add(ThemeCluster(canonical_key="late", display_name="Late",
                                     name="Late", pipeline="technical"))
            session.commit()

    with pytest.raises(LegacyThemeWritesBlocked):
        body()

    db_session.expire_all()
    assert _clusters(db_session) == 1


def test_marked_request_session_write_fails_closed_after_cutover(db_session):
    _authority(db_session, "legacy")
    mark_legacy_theme_writer(db_session)
    _switch_to_economic()

    db_session.add(ThemeCluster(canonical_key="late", display_name="Late",
                                name="Late", pipeline="technical"))
    with pytest.raises(LegacyThemeWritesBlocked):
        db_session.flush()


def test_unmarked_sessions_are_not_fenced(db_session):
    # Economic producers and ingestion keep writing shared tables.
    _authority(db_session, "economic")

    db_session.add(ThemeCluster(canonical_key="other", display_name="Other",
                                name="Other", pipeline="technical"))
    db_session.flush()


@pytest.mark.parametrize("mode", sorted(LEGACY_WRITE_MODES))
def test_task_guard_runs_the_body_in_legacy_write_modes(db_session, mode):
    _authority(db_session, mode)

    @skip_in_economic_authority
    def body(value):
        return {"status": "ran", "value": value}

    assert body(3) == {"status": "ran", "value": 3}


GUARDED_ROUTES = [
    ("POST", "/pipeline/run"),
    ("POST", "/extract"),
    ("POST", "/calculate-metrics"),
    ("POST", "/validate-all"),
    ("POST", "/equivalence"),
    ("POST", "/equivalence/op-1/undo"),
    ("POST", "/alerts/1/dismiss"),
    ("POST", "/alerts/1/read"),
    ("POST", "/alerts/check"),
    ("POST", "/merge-suggestions/1/approve"),
    ("POST", "/merge-suggestions/1/reject"),
    ("POST", "/consolidate"),
    ("POST", "/consolidate/async"),
    ("POST", "/embeddings/refresh-campaign"),
    ("POST", "/merge-wave/strict-auto"),
    ("POST", "/merge-wave/manual-review"),
    ("POST", "/candidates/review"),
    ("POST", "/create-from-cluster"),
    ("POST", "/1/add-constituents"),
    ("DELETE", "/1"),
    ("POST", "/taxonomy/assign"),
    ("POST", "/taxonomy/assign/async"),
    ("PUT", "/taxonomy/1/reassign"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", GUARDED_ROUTES, ids=[f"{m} {p}" for m, p in GUARDED_ROUTES])
async def test_route_returns_409_under_economic_authority(db_session, monkeypatch, method, path):
    from app.api.v1.config import settings as config_settings
    from app.services import server_auth

    monkeypatch.setattr(server_auth.settings, "server_auth_enabled", False)
    # Admin-only routes authenticate before the authority check.
    monkeypatch.setattr(config_settings, "admin_api_key", "admin-secret")
    _authority(db_session, "economic")
    before = _clusters(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.request(
                method, f"/api/v1/themes{path}", json={},
                headers={"X-Admin-Key": "admin-secret"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "economic_generation_endpoint_required"
    assert _clusters(db_session) == before


def test_skipped_pipeline_run_is_recorded_as_skipped(db_session):
    from app.models.theme import ThemePipelineRun

    _authority(db_session, "economic")
    db_session.add(ThemePipelineRun(run_id="run-1", pipeline="technical", status="queued"))
    db_session.commit()

    result = theme_discovery_tasks.run_full_pipeline(run_id="run-1", pipeline="technical")

    db_session.expire_all()
    run = db_session.query(ThemePipelineRun).filter_by(run_id="run-1").one()
    assert result["reason"] == ECONOMIC_AUTHORITY_SKIP_REASON
    assert run.status == "skipped"
    assert run.completed_at is not None
    assert ECONOMIC_AUTHORITY_SKIP_REASON in run.error_message


def _load(path):
    import importlib
    import importlib.util
    from pathlib import Path

    if path.startswith("app/"):  # a package module (e.g. one defining dataclasses)
        return importlib.import_module(path[:-3].replace("/", "."))
    full = Path(__file__).resolve().parents[2] / path
    spec = importlib.util.spec_from_file_location(full.stem, full)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARDED_CLIS = [
    ("scripts/backfill_l1_taxonomy.py", []),
    ("scripts/backfill_silent_failures.py", []),
    ("scripts/backfill_theme_aliases.py", ["--yes"]),
    ("app/scripts/repair_jp_alpha_universe_symbols.py", ["--apply"]),
]


@pytest.mark.parametrize("path,argv", GUARDED_CLIS, ids=[p.rsplit("/", 1)[-1] for p, _ in GUARDED_CLIS])
def test_cli_refuses_to_write_under_economic_authority(db_session, monkeypatch, capsys, path, argv):
    _authority(db_session, "economic")
    module = _load(path)
    for name in ("initialize_process_runtime_services",):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, lambda: None)
    if hasattr(module, "get_session_factory"):
        monkeypatch.setattr(module, "get_session_factory", lambda: lambda: db_session)
    monkeypatch.setattr(sys, "argv", [path, *argv])

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 1
    assert "STOP:" in capsys.readouterr().err
    assert _clusters(db_session) == 1


def test_content_storage_reset_is_refused_under_economic_authority(db_session, monkeypatch):
    _authority(db_session, "economic")
    monkeypatch.setattr(recovery, "_reset_blocked_by_authority", lambda conn: True)
    dropped = []
    monkeypatch.setattr(recovery, "drop_theme_content_tables", lambda conn: dropped.append(conn))

    with pytest.raises(LegacyThemeWritesBlocked):
        recovery.reset_corrupt_theme_content_storage(
            DatabaseError("SELECT 1", {}, Exception("database disk image is malformed"))
        )

    assert dropped == []


def test_reset_check_reads_the_authority_mode(db_session):
    _authority(db_session, "economic")

    assert recovery._reset_blocked_by_authority(db_session.connection()) is True
