"""Refresh and export the root-global static COT bundle independently."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.database import SessionLocal
from app.scripts._runtime import prepare_runtime
from app.services.static_cot_exporter import StaticCotExporter
from app.use_cases.cot.refresh import CotRefreshCommand
from app.wiring.bootstrap import get_cot_queries, get_refresh_cot_use_case


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    prepare_runtime()
    generated_at = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    with SessionLocal() as db:
        refresh = get_refresh_cot_use_case(db).execute(
            CotRefreshCommand(origin="static_build", force=False)
        )
        if refresh.status == "failed_quality":
            reasons = ", ".join(refresh.reason_codes) or "unknown"
            raise RuntimeError(
                "COT refresh failed: "
                f"status={refresh.status}, run_id={refresh.run_id}, "
                f"reason_codes={reasons}"
            )
        index = StaticCotExporter(get_cot_queries(db)).export(
            args.output_dir,
            generated_at=generated_at,
        )

    print(
        "Static COT export complete: "
        f"status={refresh.status}, publication_id={index['publication_id']}, "
        f"report_date={index['report_date']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
