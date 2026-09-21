"""Run the exact, zero-skip PostgreSQL release gate for Economic Taxonomy."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
DEFAULT_MANIFEST = BACKEND_ROOT / "tests/required_economic_taxonomy_postgres.txt"
READER_CONTRACT_FILES = (
    BACKEND_ROOT / "tests/unit/test_economic_theme_consumer_cutover.py",
    BACKEND_ROOT / "tests/unit/test_economic_theme_read_service.py",
    REPOSITORY_ROOT / "frontend/src/api/economicThemes.test.js",
    REPOSITORY_ROOT
    / "frontend/src/features/themes/components/EconomicThemeDetailModal.test.jsx",
    REPOSITORY_ROOT
    / "frontend/src/components/Themes/EconomicTaxonomyReview.test.jsx",
    REPOSITORY_ROOT / "frontend/src/pages/ThemesPage.test.jsx",
)


@dataclass(frozen=True)
class GateResult:
    exit_code: int
    required_nodes: tuple[str, ...]
    collected_nodes: tuple[str, ...]
    missing_nodes: tuple[str, ...]
    outcomes: dict[str, str]
    database: dict
    reason: str | None


class _CollectionPlugin:
    def __init__(self) -> None:
        self.node_ids: set[str] = set()

    def pytest_collection_finish(self, session) -> None:
        self.node_ids = {item.nodeid for item in session.items}


class _OutcomePlugin:
    def __init__(self) -> None:
        self.outcomes: dict[str, str] = {}

    def pytest_runtest_logreport(self, report) -> None:
        if report.when == "call":
            if hasattr(report, "wasxfail"):
                outcome = "xpassed" if report.passed else "xfailed"
            elif report.passed:
                outcome = "passed"
            elif report.skipped:
                outcome = "skipped"
            else:
                outcome = "failed"
            self.outcomes[report.nodeid] = outcome
        elif report.when == "setup" and (report.failed or report.skipped):
            self.outcomes[report.nodeid] = (
                "xfailed"
                if hasattr(report, "wasxfail")
                else "skipped"
                if report.skipped
                else "failed"
            )
        elif report.when == "teardown" and report.failed:
            self.outcomes[report.nodeid] = "failed"


def load_required_nodes(path: Path = DEFAULT_MANIFEST) -> tuple[str, ...]:
    rows = tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not rows:
        raise ValueError("required_node_manifest_empty")
    if len(set(rows)) != len(rows):
        raise ValueError("duplicate_required_node")
    if any("::" not in row for row in rows):
        raise ValueError("invalid_required_node_id")
    return rows


def _collect_nodes(nodes: tuple[str, ...]) -> tuple[int, set[str]]:
    plugin = _CollectionPlugin()
    exit_code = pytest.main(
        ["--collect-only", "-q", "--disable-warnings", *nodes],
        plugins=[plugin],
    )
    return int(exit_code), plugin.node_ids


def _execute_nodes(nodes: tuple[str, ...]) -> tuple[int, dict[str, str]]:
    plugin = _OutcomePlugin()
    exit_code = pytest.main(
        ["-q", "--disable-warnings", *nodes],
        plugins=[plugin],
    )
    return int(exit_code), plugin.outcomes


def verify_postgresql_identity(database_url: str | None = None) -> dict:
    raw_url = database_url or os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("database_url_required")
    url = make_url(raw_url)
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError("postgresql_required")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database, version = connection.execute(
                text(
                    "SELECT current_database(), "
                    "current_setting('server_version_num')::integer"
                )
            ).one()
    finally:
        engine.dispose()
    if not database or int(version) <= 0:
        raise RuntimeError("postgresql_identity_unverified")
    return {
        "dialect": "postgresql",
        "database": database,
        "server_version_num": int(version),
    }


def _ordered(required: tuple[str, ...], observed: Iterable[str]) -> tuple[str, ...]:
    values = set(observed)
    return tuple(node for node in required if node in values)


def run_required_tests(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    collect_nodes: Callable[[tuple[str, ...]], tuple[int, set[str]]] = _collect_nodes,
    execute_nodes: Callable[
        [tuple[str, ...]], tuple[int, dict[str, str]]
    ] = _execute_nodes,
    verify_database: Callable[[], dict] = verify_postgresql_identity,
) -> GateResult:
    try:
        required = load_required_nodes(manifest_path)
    except (OSError, ValueError) as exc:
        return GateResult(2, (), (), (), {}, {}, str(exc))

    try:
        database = verify_database()
    except (OSError, RuntimeError, ValueError) as exc:
        return GateResult(2, required, (), (), {}, {}, str(exc))
    if database.get("dialect") != "postgresql" or not database.get("database"):
        return GateResult(
            2,
            required,
            (),
            (),
            {},
            database,
            "postgresql_identity_unverified",
        )

    collect_exit, collected = collect_nodes(required)
    missing = tuple(node for node in required if node not in collected)
    ordered_collected = _ordered(required, collected)
    if collect_exit != 0 or missing:
        return GateResult(
            2,
            required,
            ordered_collected,
            missing,
            {},
            database,
            "required_node_collection_failed",
        )

    test_exit, outcomes = execute_nodes(required)
    normalized = {node: outcomes.get(node, "not_run") for node in required}
    nonpassing = {
        node: outcome for node, outcome in normalized.items() if outcome != "passed"
    }
    if test_exit != 0 or nonpassing:
        return GateResult(
            1,
            required,
            ordered_collected,
            (),
            normalized,
            database,
            "required_node_did_not_pass",
        )
    return GateResult(
        0,
        required,
        ordered_collected,
        (),
        normalized,
        database,
        None,
    )


def reader_consumer_test_hash(paths: Iterable[Path] = READER_CONTRACT_FILES) -> str:
    digest = sha256()
    for path in sorted((Path(value) for value in paths), key=lambda value: str(value)):
        resolved = path.resolve()
        try:
            label = resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
        except ValueError:
            label = resolved.name
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_reader_release_checks() -> int:
    commands = (
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_economic_theme_read_service.py",
                "tests/unit/test_economic_theme_consumer_cutover.py",
            ],
            BACKEND_ROOT,
        ),
        (
            [
                "npm",
                "run",
                "test:run",
                "--",
                "src/api/economicThemes.test.js",
                "src/features/themes/components/EconomicThemeDetailModal.test.jsx",
                "src/components/Themes/EconomicTaxonomyReview.test.jsx",
                "src/pages/ThemesPage.test.jsx",
            ],
            REPOSITORY_ROOT / "frontend",
        ),
        (["npm", "run", "build"], REPOSITORY_ROOT / "frontend"),
    )
    for command, cwd in commands:
        completed = subprocess.run(command, cwd=cwd, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def register_reader_capability(
    *,
    verified_by: str,
    consumer_test_hash: str,
    database_url: str,
):
    if not verified_by.strip():
        raise ValueError("verified_by_required")
    from app.models.economic_taxonomy_runtime import ReaderCapabilityManifest

    target_url = make_url(database_url)
    if target_url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError("capability_target_must_be_postgresql")
    target_engine = create_engine(target_url, pool_pre_ping=True)
    target_sessions = sessionmaker(bind=target_engine, expire_on_commit=False)
    try:
        with target_sessions() as session:
            existing = session.scalar(
                select(ReaderCapabilityManifest).where(
                    ReaderCapabilityManifest.backend_contract == 1,
                    ReaderCapabilityManifest.frontend_contract == 1,
                    ReaderCapabilityManifest.migration_version == "0054",
                    ReaderCapabilityManifest.consumer_test_hash == consumer_test_hash,
                )
            )
            if existing is not None:
                return existing.id
            capability = ReaderCapabilityManifest(
                backend_contract=1,
                frontend_contract=1,
                migration_version="0054",
                consumer_test_hash=consumer_test_hash,
                verified_by=verified_by,
            )
            session.add(capability)
            session.commit()
            return capability.id
    finally:
        target_engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--register-reader-capability", action="store_true")
    parser.add_argument(
        "--capability-database-url",
        default=os.environ.get("CAPABILITY_DATABASE_URL"),
        help="Migrated target database; required only when registering capability.",
    )
    parser.add_argument("--verified-by")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_required_tests(args.manifest)
    payload = asdict(result)
    if result.exit_code == 0:
        payload["reader_consumer_test_hash"] = reader_consumer_test_hash()
    if args.register_reader_capability and result.exit_code == 0:
        if not args.verified_by:
            payload["reason"] = "verified_by_required"
            result_code = 2
        elif not args.capability_database_url:
            payload["reason"] = "capability_database_url_required"
            result_code = 2
        else:
            release_exit = run_reader_release_checks()
            if release_exit != 0:
                payload["reason"] = "reader_release_checks_failed"
                result_code = release_exit
            else:
                capability_id = register_reader_capability(
                    verified_by=args.verified_by,
                    consumer_test_hash=payload["reader_consumer_test_hash"],
                    database_url=args.capability_database_url,
                )
                payload["reader_capability_manifest_id"] = str(capability_id)
                result_code = 0
    else:
        result_code = result.exit_code
    payload["exit_code"] = result_code
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
