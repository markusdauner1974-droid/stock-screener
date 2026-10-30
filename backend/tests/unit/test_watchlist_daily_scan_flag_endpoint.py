from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.services import server_auth


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(server_auth.settings, "server_auth_enabled", False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_daily_scan_flag_round_trips_through_update_and_list(client):
    created = (await client.post("/api/v1/user-watchlists/", json={"name": "Leaders"})).json()
    assert created["include_in_daily_scan"] is False

    flagged = await client.put(
        f"/api/v1/user-watchlists/{created['id']}", json={"include_in_daily_scan": True}
    )
    assert flagged.status_code == 200
    assert flagged.json()["include_in_daily_scan"] is True

    renamed = await client.put(f"/api/v1/user-watchlists/{created['id']}", json={"name": "Leaders 2"})
    assert renamed.json()["include_in_daily_scan"] is True

    listed = (await client.get("/api/v1/user-watchlists/")).json()["watchlists"]
    assert [(w["name"], w["include_in_daily_scan"]) for w in listed] == [("Leaders 2", True)]

    await client.put(f"/api/v1/user-watchlists/{created['id']}", json={"include_in_daily_scan": False})
    listed = (await client.get("/api/v1/user-watchlists/")).json()["watchlists"]
    assert [w["include_in_daily_scan"] for w in listed] == [False]


@pytest.mark.asyncio
async def test_deleting_a_watchlist_deletes_its_daily_scans(client, db_session):
    from app.database import SessionLocal
    from app.models.scan_result import SCAN_TRIGGER_SOURCE_WATCHLIST, Scan, ScanResult
    from app.models.ui_view_snapshot import UIViewSnapshot, UIViewSnapshotPointer
    from app.services.ui_snapshot_service import UISnapshotService

    gone = (await client.post("/api/v1/user-watchlists/", json={"name": "Gone"})).json()["id"]
    kept = (await client.post("/api/v1/user-watchlists/", json={"name": "Kept"})).json()["id"]
    daily_scans = {
        "gone-us": f"watchlist:{gone}:US",
        "gone-hk": f"watchlist:{gone}:HK",
        "kept-us": f"watchlist:{kept}:US",
        # Another watchlist whose id starts with the deleted one's digits.
        "decoy-us": f"watchlist:{gone}0:US",
    }
    for scan_id, universe_key in daily_scans.items():
        db_session.add(Scan(
            scan_id=scan_id, status="completed", universe_type="custom", universe_key=universe_key,
            universe_market=universe_key.rsplit(":", 1)[1], universe_symbols=["AAPL"],
            trigger_source=SCAN_TRIGGER_SOURCE_WATCHLIST, total_stocks=1, passed_stocks=1,
        ))
    db_session.commit()
    for scan_id in daily_scans:
        UISnapshotService(SessionLocal).publish_scan_bootstraps_for(scan_id, with_latest=False)
        db_session.add(ScanResult(scan_id=scan_id, symbol="AAPL"))
    db_session.commit()

    resp = await client.delete(f"/api/v1/user-watchlists/{gone}")

    assert resp.status_code == 200
    listed = (await client.get("/api/v1/user-watchlists/")).json()["watchlists"]
    assert [w["name"] for w in listed] == ["Kept"]
    remaining = ["decoy-us", "kept-us"]
    assert sorted(s for (s,) in db_session.query(Scan.scan_id)) == remaining
    assert sorted(s for (s,) in db_session.query(ScanResult.scan_id)) == remaining
    assert sorted(v for (v,) in db_session.query(UIViewSnapshot.variant_key)) == ["scan:decoy-us", "scan:kept-us"]
    assert sorted(v for (v,) in db_session.query(UIViewSnapshotPointer.variant_key)) == ["scan:decoy-us", "scan:kept-us"]
