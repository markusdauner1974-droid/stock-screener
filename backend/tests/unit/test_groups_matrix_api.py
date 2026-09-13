import httpx
import pytest
from app.api.v1.groups import router
from app.database import get_db
from app.models.industry import IBDIndustryGroup
from fastapi import FastAPI

from tests.unit.test_group_matrix_service import (
    add_run,
    matrix_db,  # noqa: F401
)


@pytest.mark.asyncio
async def test_matrix_route_normalizes_market_and_reports_unavailable(db):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/groups")
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/groups/matrix?market=hk")
        assert response.status_code == 200
        assert response.json()["market"] == "HK"
        assert response.json()["reason"] == "no_published_run"
        assert (
            await client.get("/api/v1/groups/matrix?market=WRONG")
        ).status_code == 400
        add_run(db, 1, "HK", ["A.HK"])
        db.add(IBDIndustryGroup(symbol="A.HK", market="HK", industry_group="Software"))
        db.commit()
        payload = (await client.get("/api/v1/groups/matrix?market=HK")).json()
        assert payload["stocks"][0]["symbol"] == "A.HK"
        assert payload["feature_run_id"] == 1


@pytest.mark.asyncio
async def test_matrix_database_failure_is_not_reported_as_empty_data(db, monkeypatch):
    from app.services.group_matrix_repository import GroupMatrixRepository
    from sqlalchemy.exc import SQLAlchemyError

    add_run(db, 1, "US", ["A"])

    def fail(*args, **kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(GroupMatrixRepository, "load_rows", fail)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/groups")
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/v1/groups/matrix?market=US")).status_code == 500
