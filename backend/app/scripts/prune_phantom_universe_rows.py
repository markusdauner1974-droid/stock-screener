"""One-time prune of phantom ``StockUniverse`` rows that collapse on canonicalization.

A row is a *phantom* when its stored symbol re-canonicalizes (via the security
master resolver) to a *different* symbol that already exists as its own row — e.g.
a TW ``1240.TW`` row carrying the ``TPEX`` board, which canonicalizes to
``1240.TWO`` (the genuine sibling). The shared TW MIC ``XTAI`` never rewrites a
board suffix, so ``.TW``/``.TWO`` rows stored under ``XTAI`` are not phantoms.
Such duplicates are what crashed weekly-bundle
import on the ``StockUniverse.symbol`` unique index; the import path now collapses
them automatically, so published bundles self-heal on the next weekly cycle. This
script is for any *persistent* universe DB (local dev, a long-running deployment)
that won't re-import a bundle soon and should be cleaned proactively.

Idempotent and safe to re-run. A genuine standalone ``.TWO`` (exchange ``TPEX``,
no ``.TW`` sibling) canonicalizes to itself and is never pruned.

Usage:
    python -m app.scripts.prune_phantom_universe_rows [--market TW] [--dry-run]
"""
from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.stock_universe import StockUniverse
from app.scripts._runtime import prepare_runtime
from app.services.security_master_service import security_master_resolver


def _canonical_symbol(row: StockUniverse) -> str:
    return security_master_resolver.resolve_identity(
        symbol=str(row.symbol or ""),
        market=row.market,
        exchange=row.exchange,
    ).canonical_symbol


def prune_phantom_universe_rows(
    db: Session,
    *,
    market: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Delete universe rows whose symbol canonicalizes onto a different existing row.

    Pure DB orchestration so it's unit-testable without a live database. Returns
    ``{"scanned", "phantoms", "deleted"}``.
    """
    query = db.query(StockUniverse)
    if market:
        query = query.filter(StockUniverse.market == market.strip().upper())
    rows = query.all()

    present = {row.symbol for row in rows}
    phantoms = [
        row
        for row in rows
        if (canonical := _canonical_symbol(row)) != row.symbol and canonical in present
    ]

    if not dry_run:
        for row in phantoms:
            db.delete(row)
        db.commit()

    return {"scanned": len(rows), "phantoms": len(phantoms), "deleted": 0 if dry_run else len(phantoms)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default=None, help="Restrict to one market (e.g. TW).")
    parser.add_argument("--dry-run", action="store_true", help="Report phantoms without deleting.")
    args = parser.parse_args(argv)

    prepare_runtime()
    with SessionLocal() as db:
        stats = prune_phantom_universe_rows(db, market=args.market, dry_run=args.dry_run)

    print("Phantom universe-row prune complete:")
    for key, value in stats.items():
        print(f"  - {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
