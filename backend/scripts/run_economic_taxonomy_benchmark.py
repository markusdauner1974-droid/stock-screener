"""Run the fail-closed Economic Taxonomy contract benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.economic_taxonomy_benchmark import evaluate_benchmark


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--taxonomy-hash", required=True)
    parser.add_argument("--policy-bundle", required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixtures = json.loads(args.fixtures.read_text())
    actual = json.loads(args.actual.read_text())
    report = evaluate_benchmark(
        fixtures,
        actual,
        taxonomy_hash=args.taxonomy_hash,
        policy_bundle=args.policy_bundle,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.write_text(rendered)
    else:
        print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
