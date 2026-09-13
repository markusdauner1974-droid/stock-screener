"""Optional Matrix asset publication and artifact-boundary validation."""

import json
from pathlib import Path

from sqlalchemy import inspect

from app.schemas.group_matrix import GroupMatrixResponse


def export_group_matrix(db, *, output_dir, market, feature_run_id, generated_at):
    # Artifact validation also runs in standalone jobs without a database.
    # Import runtime database services only when exporting from a live session.
    from app.services.group_matrix_service import GroupMatrixService

    # Older/minimal artifact databases may not include feature membership or IBD.
    required = {
        "feature_runs",
        "feature_run_universe_symbols",
        "stock_feature_daily",
        "stock_universe",
        "stock_fundamentals",
        "ibd_industry_groups",
    }
    if not required.issubset(set(inspect(db.get_bind()).get_table_names())):
        return None
    payload = GroupMatrixService().build(
        db, market=market, feature_run_id=feature_run_id, generated_at=generated_at
    )
    if not payload["available"]:
        return None
    relative = Path("markets") / market.lower() / "groups_matrix.json"
    target = Path(output_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {"path": relative.as_posix()}


def validate_group_matrix_asset(*, market, market_dir, entry):
    asset = (entry.get("assets") or {}).get("groups_matrix")
    if asset is None:
        return
    expected_path = f"markets/{market.lower()}/groups_matrix.json"
    if not isinstance(asset, dict) or asset.get("path") != expected_path:
        raise ValueError("Invalid Matrix asset path")
    target = Path(market_dir) / "groups_matrix.json"
    if target.resolve().parent != Path(market_dir).resolve():
        raise ValueError("Matrix asset escapes market directory")
    payload = GroupMatrixResponse.model_validate_json(
        target.read_text(encoding="utf-8")
    )
    if not payload.available or payload.market != market:
        raise ValueError("Matrix asset identity does not match market")
    for key in (
        "feature_run_id",
        "as_of_date",
        "rs_formula_version",
        "market_rs_run_id",
        "rs_universe_size",
    ):
        if getattr(payload, key) != entry.get(key):
            raise ValueError(f"Matrix asset identity mismatch: {key}")
    if (
        payload.feature_run_id is None
        or payload.as_of_date is None
        or payload.rs_formula_version is None
    ):
        raise ValueError("Matrix asset has incomplete publication identity")
    symbols = {s.symbol for s in payload.stocks}
    if len(symbols) != len(payload.stocks) or payload.coverage.stock_count != len(
        payload.stocks
    ):
        raise ValueError("Matrix asset coverage does not match stocks")
