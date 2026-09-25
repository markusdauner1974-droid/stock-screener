import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import economic_themes
from app.database import get_db

from .economic_taxonomy_reader_helpers import seed_generation


async def _get(db_session, path, *, params=None):
    app = FastAPI()
    app.include_router(economic_themes.router, prefix="/api/v1/economic-themes")

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path, params=params)


@pytest.mark.asyncio
async def test_snapshot_bundle_uses_one_generation(db_session):
    seeded = seed_generation(db_session)

    payload = (await _get(db_session, "/api/v1/economic-themes")).json()

    assert payload["generation_id"] == str(seeded["generation"].id)
    assert payload["taxonomy_version_id"] == payload["generation"][
        "taxonomy_version_id"
    ]
    assert payload["generation_input_manifest_hash"] == payload["generation"][
        "generation_input_manifest_hash"
    ]
    assert payload["themes"][0]["metrics"]["narrative_attention"][
        "availability"
    ] == "available"


@pytest.mark.asyncio
async def test_historical_generation_is_reproducible(db_session):
    old = seed_generation(db_session, display_name="Old Memory")
    current = seed_generation(db_session, display_name="Current Memory")

    response = await _get(
        db_session,
        f"/api/v1/economic-themes?generation_id={old['generation'].id}"
    )

    assert response.status_code == 200
    assert response.json()["generation_id"] == str(old["generation"].id)
    assert response.json()["themes"][0]["display_name"] == "Old Memory"
    assert response.json()["generation_id"] != str(current["generation"].id)


@pytest.mark.asyncio
async def test_interpretation_set_without_generation_is_not_a_product_read(
    db_session,
):
    seeded = seed_generation(db_session)

    response = await _get(
        db_session,
        "/api/v1/economic-themes",
        params={"interpretation_set_id": seeded["interpretation"].id},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_generation_is_not_found(db_session):
    from uuid import uuid4

    seed_generation(db_session)
    response = await _get(
        db_session,
        "/api/v1/economic-themes",
        params={"generation_id": uuid4()},
    )
    assert response.status_code == 404
