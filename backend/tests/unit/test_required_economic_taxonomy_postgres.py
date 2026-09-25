from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_required_economic_taxonomy_postgres import (
    GateResult,
    load_required_nodes,
    reader_consumer_test_hash,
    register_reader_capability,
    run_required_tests,
)


def _manifest(tmp_path: Path, *nodes: str) -> Path:
    path = tmp_path / "required.txt"
    path.write_text("# required\n" + "\n".join(nodes) + "\n", encoding="utf-8")
    return path


def test_manifest_ignores_comments_and_rejects_duplicates(tmp_path):
    path = _manifest(tmp_path, "test_a.py::test_one", "", "test_b.py::test_two")
    assert load_required_nodes(path) == (
        "test_a.py::test_one",
        "test_b.py::test_two",
    )

    duplicate = _manifest(tmp_path, "test_a.py::test_one", "test_a.py::test_one")
    with pytest.raises(ValueError, match="duplicate_required_node"):
        load_required_nodes(duplicate)


@pytest.mark.parametrize("outcome", ["skipped", "xfailed", "failed", "xpassed"])
def test_required_gate_rejects_every_non_pass_outcome(tmp_path, outcome):
    manifest = _manifest(tmp_path, "tests/test_cutover.py::test_cutover_race")

    result = run_required_tests(
        manifest,
        collect_nodes=lambda _nodes: (
            0,
            {"tests/test_cutover.py::test_cutover_race"},
        ),
        execute_nodes=lambda _nodes: (
            0,
            {"tests/test_cutover.py::test_cutover_race": outcome},
        ),
        verify_database=lambda: {"dialect": "postgresql", "database": "ci"},
    )

    assert result.exit_code != 0
    assert result.outcomes["tests/test_cutover.py::test_cutover_race"] == outcome


def test_required_gate_rejects_missing_collection_and_non_postgres(tmp_path):
    manifest = _manifest(tmp_path, "tests/test_cutover.py::test_cutover_race")

    missing = run_required_tests(
        manifest,
        collect_nodes=lambda _nodes: (0, set()),
        execute_nodes=lambda _nodes: (0, {}),
        verify_database=lambda: {"dialect": "postgresql", "database": "ci"},
    )
    wrong_database = run_required_tests(
        manifest,
        collect_nodes=lambda nodes: (0, set(nodes)),
        execute_nodes=lambda nodes: (0, dict.fromkeys(nodes, "passed")),
        verify_database=lambda: {"dialect": "sqlite", "database": ":memory:"},
    )

    assert missing.exit_code != 0
    assert missing.missing_nodes == ("tests/test_cutover.py::test_cutover_race",)
    assert wrong_database.exit_code != 0


def test_required_gate_accepts_only_exact_all_pass_postgres_run(tmp_path):
    nodes = (
        "tests/test_cutover.py::test_cutover_race",
        "tests/test_outbox.py::test_abandoned_excluded",
    )
    result = run_required_tests(
        _manifest(tmp_path, *nodes),
        collect_nodes=lambda values: (0, set(values)),
        execute_nodes=lambda values: (0, dict.fromkeys(values, "passed")),
        verify_database=lambda: {
            "dialect": "postgresql",
            "database": "ci",
            "server_version_num": 160000,
        },
    )

    assert result == GateResult(
        exit_code=0,
        required_nodes=nodes,
        collected_nodes=nodes,
        missing_nodes=(),
        outcomes=dict.fromkeys(nodes, "passed"),
        database={
            "dialect": "postgresql",
            "database": "ci",
            "server_version_num": 160000,
        },
        reason=None,
    )


def test_reader_consumer_hash_changes_with_inventory_content(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")

    digest = reader_consumer_test_hash((first, second))
    second.write_text("changed\n", encoding="utf-8")

    assert len(digest) == 64
    assert reader_consumer_test_hash((first, second)) != digest


def test_reader_capability_target_must_be_postgresql():
    with pytest.raises(RuntimeError, match="capability_target_must_be_postgresql"):
        register_reader_capability(
            verified_by="admin:release",
            consumer_test_hash="a" * 64,
            database_url="sqlite:///:memory:",
        )
