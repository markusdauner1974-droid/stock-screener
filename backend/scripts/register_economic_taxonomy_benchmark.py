"""Register a passed Economic Taxonomy benchmark for publication."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.economic_taxonomy_benchmark_store import (
    register_verified_benchmark,
)


def register_report(session, *, report_path: Path, verified_by: str):
    report = json.loads(report_path.read_text())
    result = register_verified_benchmark(
        session,
        report=report,
        verified_by=verified_by,
    )
    session.commit()
    return result.id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--verified-by", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from app.database import SessionLocal

    with SessionLocal() as session:
        result_id = register_report(
            session,
            report_path=args.report,
            verified_by=args.verified_by,
        )
    print(str(result_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
