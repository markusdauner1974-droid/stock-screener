"""Backfill and republish the complete curated CFTC COT history."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Callable, ContextManager

from app.database import SessionLocal
from app.use_cases.cot.refresh import CotRefreshCommand
from app.wiring.bootstrap import get_refresh_cot_use_case


@contextmanager
def _default_use_case_factory() -> Iterator[Any]:
    with SessionLocal() as session:
        yield get_refresh_cot_use_case(session)


def main(
    argv: Sequence[str] | None = None,
    *,
    use_case_factory: Callable[[], ContextManager[Any]] = _default_use_case_factory,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        with use_case_factory() as use_case:
            result = use_case.execute(
                CotRefreshCommand(
                    origin="administrative_backfill",
                    force=True,
                )
            )
    except Exception as exc:
        print(json.dumps({"status": "failed_fetch", "error": type(exc).__name__}))
        return 1

    print(
        json.dumps(
            {
                "status": result.status,
                "run_id": result.run_id,
                "report_date": (
                    result.report_date.isoformat() if result.report_date else None
                ),
                "instrument_count": result.instrument_count,
                "price_unavailable_count": result.price_unavailable_count,
                "reason_codes": list(result.reason_codes),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.status in {"published", "no_change"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
