import json
from datetime import date, timedelta

from app.scripts import report_static_market_freshness as report


class _WeekdayCalendar:
    """Every weekday is a session; the last completed one is fixed."""

    def __init__(self, last_completed: date):
        self._last_completed = last_completed

    def last_completed_trading_day(self, market):
        return self._last_completed

    def trading_days(self, market, start, end):
        days, day = [], start
        while day <= end:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        return days


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_freshness_rows_rank_current_stale_and_missing_markets(tmp_path):
    # Thu 2026-10-01 is the last completed session everywhere.
    calendar = _WeekdayCalendar(date(2026, 10, 1))
    manifest = {
        "markets": {
            "US": {"as_of_date": "2026-10-01"},
            "HK": {"as_of_date": "2026-09-30"},
            "AU": {"as_of_date": "2026-09-03"},
        }
    }
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "static-market-status-US" / "status.json",
                {"market": "US", "has_current_artifact": True, "status": "published", "reason": None})
    _write_json(artifacts / "static-market-US" / "manifest.market.json",
                {"market": "US", "entry": {"as_of_date": "2026-10-01"}})
    _write_json(artifacts / "static-market-status-AU" / "status.json",
                {"market": "AU", "has_current_artifact": False, "status": "failed", "reason": "no_current_artifact"})
    _write_json(artifacts / "static-market-diagnostics-AU" / "snapshot-failure.json",
                {"market": "AU", "reason": "market_rs_not_ready"})
    bundles = tmp_path / "bundles"
    _write_json(bundles / "daily-price-latest-us.json", {"as_of_date": "2026-10-01"})
    _write_json(bundles / "daily-price-latest-hk.json", {"as_of_date": "2026-09-24"})

    rows = report.build_freshness_rows(
        manifest=manifest,
        markets=("US", "HK", "AU", "TW"),
        artifacts_dir=artifacts,
        price_manifest_dir=bundles,
        calendar=calendar,
        max_sessions_behind=3,
    )
    by_market = {row.market: row for row in rows}

    assert by_market["US"].sessions_behind == 0
    assert by_market["US"].source == "current"
    assert by_market["US"].level == "ok"

    # HK not built this run: one session behind, and its price bundle five behind.
    assert by_market["HK"].source == "previous run"
    assert by_market["HK"].sessions_behind == 1
    assert by_market["HK"].bundle_sessions_behind == 5
    assert by_market["HK"].level == "error"

    # AU fell back to a month-old artifact; the diagnostics reason wins.
    assert by_market["AU"].source == "fallback"
    assert by_market["AU"].sessions_behind == 20
    assert by_market["AU"].reason == "market_rs_not_ready"
    assert by_market["AU"].level == "error"

    # TW had no current or fallback artifact, so the site omits it.
    assert by_market["TW"].served_as_of is None
    assert by_market["TW"].source == "not served"
    assert by_market["TW"].level == "error"


def test_newer_fallback_over_a_rewound_current_artifact_is_labelled_fallback(tmp_path):
    # The TW export succeeded but rewound to 09-29; the combiner served the
    # newer 09-30 fallback instead.
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "static-market-status-TW" / "status.json",
                {"market": "TW", "has_current_artifact": True, "status": "published"})
    _write_json(artifacts / "static-market-TW" / "manifest.market.json",
                {"market": "TW", "entry": {"as_of_date": "2026-09-29"}})

    rows = report.build_freshness_rows(
        manifest={"markets": {"TW": {"as_of_date": "2026-09-30"}}},
        markets=("TW",),
        artifacts_dir=artifacts,
        price_manifest_dir=tmp_path,
        calendar=_WeekdayCalendar(date(2026, 9, 30)),
        max_sessions_behind=3,
    )

    assert rows[0].source == "fallback"


def test_selected_market_without_status_is_a_fallback_not_previous_run(tmp_path):
    # IN was built this run but its job died before uploading status.json.
    rows = report.build_freshness_rows(
        manifest={"markets": {"IN": {"as_of_date": "2026-09-03"}, "HK": {"as_of_date": "2026-10-01"}}},
        markets=("IN", "HK"),
        artifacts_dir=tmp_path,
        price_manifest_dir=tmp_path,
        calendar=_WeekdayCalendar(date(2026, 10, 1)),
        max_sessions_behind=3,
        selected_markets={"IN"},
    )
    by_market = {row.market: row for row in rows}

    assert by_market["IN"].source == "fallback"
    assert by_market["IN"].reason == "no status from this run's build"
    assert by_market["HK"].source == "previous run"


def test_one_session_behind_is_a_warning_not_an_error(tmp_path):
    rows = report.build_freshness_rows(
        manifest={"markets": {"JP": {"as_of_date": "2026-09-30"}}},
        markets=("JP",),
        artifacts_dir=tmp_path,
        price_manifest_dir=tmp_path,
        calendar=_WeekdayCalendar(date(2026, 10, 1)),
        max_sessions_behind=3,
    )

    assert rows[0].level == "warning"
    assert "JP is 1 session(s) behind" in report.annotation(rows[0])


def test_missing_price_manifest_is_a_warning_not_silence(tmp_path):
    rows = report.build_freshness_rows(
        manifest={"markets": {"US": {"as_of_date": "2026-10-01"}}},
        markets=("US",),
        artifacts_dir=tmp_path,
        price_manifest_dir=tmp_path / "empty",
        calendar=_WeekdayCalendar(date(2026, 10, 1)),
        max_sessions_behind=3,
    )

    assert rows[0].sessions_behind == 0
    assert rows[0].level == "warning"
    assert "price bundle manifest unavailable" in report.annotation(rows[0])


def test_annotation_escapes_workflow_command_characters():
    row = report.MarketFreshness(
        market="AU", served_as_of=date(2026, 9, 3), expected_session=date(2026, 10, 1),
        sessions_behind=20, price_bundle_as_of=None, bundle_sessions_behind=None,
        source="fallback", reason="85% floor\n::error::injected", level="error",
    )

    line = report.annotation(row)
    assert "\n" not in line
    assert "85%25 floor%0A::error::injected" in line


def test_main_writes_summary_table_and_annotations(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, {"markets": {"US": {"as_of_date": "2026-10-01"}}})
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setattr(report, "STATIC_SUPPORTED_MARKETS", ("US", "TW"))
    monkeypatch.setattr(report, "MarketCalendarService", lambda: _WeekdayCalendar(date(2026, 10, 1)))

    assert report.main([
        "--manifest", str(manifest_path),
        "--artifacts-dir", str(tmp_path / "missing"),
        "--price-manifest-dir", str(tmp_path / "missing"),
    ]) == 0

    summary = summary_path.read_text(encoding="utf-8")
    assert "| US | 2026-10-01 | 2026-10-01 | 0 |" in summary
    assert "| TW | — |" in summary
    assert "::error title=Static site freshness::TW is not on the site" in capsys.readouterr().out
