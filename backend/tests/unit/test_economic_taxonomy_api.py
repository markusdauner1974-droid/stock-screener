import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import economic_taxonomy
from app.database import get_db

from .economic_taxonomy_reader_helpers import seed_generation


async def _get(db_session, path):
    app = FastAPI()
    app.include_router(economic_taxonomy.router, prefix="/api/v1/economic-taxonomy")

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_review_snapshot_is_generation_scoped(db_session):
    seeded = seed_generation(db_session)

    response = await _get(db_session, "/api/v1/economic-taxonomy/review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generation_id"] == str(seeded["generation"].id)
    assert payload["relationships"][0]["direction"] == "narrower"
    assert payload["mappings"][0]["legacy_theme_cluster_id"] == 42
    assert payload["pinned_revisions"][0]["development_revision"] == 7


@pytest.mark.asyncio
async def test_generation_metadata_uses_the_same_manifest_hash(db_session):
    seeded = seed_generation(db_session)

    payload = (
        await _get(
            db_session,
        f"/api/v1/economic-taxonomy/generations/{seeded['generation'].id}"
        )
    ).json()

    assert payload["generation_input_manifest_id"] == str(seeded["manifest"].id)
    assert payload["generation_input_manifest_hash"] == seeded["manifest"].semantic_hash
    assert payload["reader_snapshot_bundle_id"] == str(seeded["bundle"].id)
