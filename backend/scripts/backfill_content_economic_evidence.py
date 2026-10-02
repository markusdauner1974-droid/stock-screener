"""Admit previously ingested news/RSS/Substack/Reddit items as economic evidence (#471).

Run once per deployment before entering shadow mode. Re-running is safe;
``--after-id`` resumes from the last id the previous run reported.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--after-id", type=int, default=0)
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    from app.services.content_ingestion_service import ContentIngestionService

    with SessionLocal() as db:
        result = ContentIngestionService(db).backfill_economic_evidence(
            batch_size=args.batch_size, after_id=args.after_id
        )
    print(f"admitted={result['admitted']} last_id={result['last_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
