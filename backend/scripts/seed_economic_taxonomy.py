"""Seed the governed V1 Economic Taxonomy snapshot (runbook step 2).

Adopts the implicit legacy authority row a fenced legacy write may already have
created; refuses a row that is already seeded. Prints the draft UUID.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", default=os.environ.get("TAXONOMY_ACTOR"))
    args = parser.parse_args(argv)
    if not args.actor:
        parser.error("--actor or TAXONOMY_ACTOR is required")

    from app.database import SessionLocal
    from app.services.economic_taxonomy_seed import SeedRefused, seed_governed_snapshot

    with SessionLocal() as db:
        try:
            draft_id = seed_governed_snapshot(db, actor=args.actor)
        except SeedRefused as exc:
            print(f"STOP: {exc}", file=sys.stderr)
            return 1
    print(draft_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
