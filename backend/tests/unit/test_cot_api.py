import pytest
from fastapi import HTTPException, Response

from tests.unit.test_cot_queries import service


def test_cot_handlers_return_catalog_history_and_snapshot(monkeypatch):
    from app.api.v1 import cot as module

    queries = service()
    monkeypatch.setattr(module, "get_cot_queries", lambda _db: queries)
    response = Response()

    catalog = module.get_cot_catalog(response=response, db=object())
    history = module.get_cot_history(
        "sp-500", response=response, range_name="1y", db=object()
    )
    snapshot = module.get_cot_snapshot(response=response, db=object())

    assert len(catalog.instruments) == 31
    assert len(history.weeks) == 52
    assert len(snapshot.rows) == 31


def test_invalid_slug_returns_stable_unavailable_code(monkeypatch):
    from app.api.v1 import cot as module

    monkeypatch.setattr(module, "get_cot_queries", lambda _db: service())

    with pytest.raises(HTTPException) as error:
        module.get_cot_history(
            "not-a-market", response=Response(), range_name="1y", db=object()
        )

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "cot_instrument_unavailable"


def test_cot_routes_are_registered_on_protected_v1_router():
    from app.api.v1.router import router

    paths = {route.path for route in router.routes}
    assert "/cot/instruments" in paths
    assert "/cot/instruments/{slug}/history" in paths
    assert "/cot/snapshot" in paths


def test_cot_catalog_requires_browser_revalidation(monkeypatch):
    from app.api.v1 import cot as module

    monkeypatch.setattr(module, "get_cot_queries", lambda _db: service())
    response = Response()

    module.get_cot_catalog(response=response, db=object())

    assert response.headers["Cache-Control"] == "private, no-cache"


def test_cot_history_keeps_short_private_browser_cache(monkeypatch):
    from app.api.v1 import cot as module

    monkeypatch.setattr(module, "get_cot_queries", lambda _db: service())
    response = Response()

    module.get_cot_history(
        "sp-500", response=response, range_name="1y", db=object()
    )

    assert response.headers["Cache-Control"] == "private, max-age=60"
