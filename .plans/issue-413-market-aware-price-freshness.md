# #413 — Market-aware price-cache freshness

## Problem (verified on `main` @ aa9ff242)

Every price-cache freshness decision uses the US Eastern clock and the NYSE calendar:

| Stage | Code | US-only behaviour |
|---|---|---|
| Metadata write | `_store_fetch_metadata` (L835), `store_batch_in_cache` (L1615) | `needs_refresh_after_close = utils.market_hours.is_market_open(now_et)` |
| Metadata read | `PriceCacheFreshnessPolicy.is_fetch_metadata_stale` (L45) | stale iff flag set and now ≥ 16:30 ET with NYSE closed |
| Expected session | `_get_expected_data_date` (L1219) | NYSE sessions with a 16:30 ET cut-off |
| Cache-only reads | `get_cached_only_fresh` (L232), `get_many_cached_only_fresh` (L292) | call the above without a market, and read the `price:US:*` metadata key |
| Stale scan | `get_stale_intraday_symbols` | US hours; drops the market from the key |

**Data-corruption consequence.** An HK bar fetched during the HK session (while the US is closed) is stamped `closing`. `_fetch_incremental_and_merge` only takes rows *after* `last_cached_date` unless `force_same_day_refresh` is set, so the partial bar is never overwritten and a wrong close is kept in `stock_prices` permanently.

## Design

### 1. Judge staleness from `fetch_timestamp`, not the stored flag

A cached bar for trading day **D** (in the market's local time) is **partial** when it was fetched on D before D's session close + 30 minutes. That buffer matches `MarketCalendarService.last_completed_trading_day`. The bar is **stale** when it is partial *and* D's session has since completed (`D <= last_completed_trading_day(market)`).

- The rule is "fetched before close + buffer", not "market open at fetch time", because a lunch-break fetch (HK, JP, CN) also holds a partial bar. This was found by the `9988.HK` test at 12:00 HKT.
- Implemented as `PriceCacheFreshnessPolicy.partial_session_day()`. Readers and writers share it, so the stored flag and the reader verdict can't disagree.

- The evaluation ignores `needs_refresh_after_close`. Existing metadata written under US rules still has `fetch_timestamp`, so misclassified HK/JP/TW partial bars are **re-judged correctly with no key bump**. This covers every entry still inside the metadata TTL (7 days).
- Old ET-only timestamps are converted with `datetime.fromisoformat`; they carry an offset.
- Calendar errors (`CalendarCoverageExpired`, `CalendarScheduleUnavailable`, `ValueError`) → **stale**. This matches today's `expected is None → stale` and the API gate's `calendar_unavailable` stance.

### 2. Expected session per market

`expected_data_date(market) = MarketCalendarService.last_completed_trading_day(market)`, returning `None` on calendar error, which means stale. For US this matches the current rule (close + 30m), except that early-close days now expect the same day from 13:30 ET, which is correct.

### 3. Thread the market through every read and write
- Writers (`_store_fetch_metadata`, `store_batch_in_cache`) keep writing the same payload, adding `market`. The flag is still written for backward compatibility with readers still running during rollout.
- Readers resolve the market per symbol: from an explicit `market` argument, from `market_by_symbol`, or else from `_active_market_by_symbol`. Metadata keys and the expected session then use that market.
- `get_stale_intraday_symbols` parses the market out of `price:{MARKET}:{SYMBOL}:fetch_meta` and applies rule 1 per market, so the after-close refresh job also re-fetches misclassified non-US bars. That job does a full 2y re-fetch, which overwrites them.
- Unchanged: `get_symbols_needing_refresh` (elapsed-hours comparison of aware timestamps, already market-neutral) and the SPY cache-health check, which stays US.

### 3b. Resilience
- On a calendar failure, **US** falls back to the pre-calendar US-clock rule (`_legacy_us_expected_data_date`, `_legacy_us_metadata_stale`), so US behaviour survives a calendar outage. Non-US markets → stale.
- `_calendar()` uses the process-scoped `MarketCalendarService`, or a standalone instance when runtime services were never initialized (scripts).
- On the Redis bulk path, `expected_date is None` now means stale, not fresh, matching the DB path. US is unaffected because its fallback never returns `None`.

### 3c. Performance
Calendar calls cost about 1.5–2 ms each, and bulk paths judge thousands of symbols. The first cut added about 10 s per 5,000-symbol `get_many`. The policy now memoizes:
- **settlement cutoffs:** per (market, session day), for the process lifetime, because they never change;
- **last completed session:** per explicit `now`, or reused for 5 s when read from the clock.

Result: about 0.014 ms per freshness check (0.07 s per 5,000 symbols). Pinned by `test_bulk_freshness_checks_reuse_calendar_answers`.

### US behaviour deltas (intentional, small)
1. **Early-close days:** the expected session follows the half-day close (13:00 + 30m) instead of 16:30 ET.
2. **Fetches between 16:00 and 16:30 ET:** now partial, so one extra re-fetch after 16:30. Consistent with the settlement buffer the expected-session rule already applies.
3. **Pre-market fetches on a trading day:** flagged for the after-close stale refresh. That data is already stale by date after the close.
4. **The morning after:** a mid-session bar from the previous session is detected as stale at any time. The old rule only flagged it after 16:30 ET, and the incremental merge then kept the partial bar permanently.

### 4. Missing metadata stays trusted (deliberate; decided 2026-09-30)
The daily-price bundle and the static daily refresh persist final end-of-day bars **without** Redis metadata (`persist_stock_price_mappings`). Treating missing metadata as unverified would mark every bundle-hydrated symbol stale and break cache-only scans (409 `market_data_stale`). So rule 1 applies only when metadata exists.

### 5. Existing damage older than the metadata TTL: no repair (decided 2026-09-30)
Partial bars whose metadata has expired cannot be identified from the cache. Once a newer bar exists they persist, because `persist_stock_price_mappings` rewrites older rows only when the close matches (a split-safety rule). Damage only happens when a non-US symbol is fetched live during its own session, and each occurrence is a single bar. The static site is unaffected: it builds after each market group's close and keys on `as_of_date`, not on the Redis intraday metadata. Most users run the app for US markets, so **no repair script**. This fix stops new occurrences, and metadata still within its TTL is re-judged automatically.

## Tests (write first)
- HK fetch during the HK session → stale after the HK close + 30m; fresh before it.
- HK fetch after the HK close → fresh, even while the US market is open (the old rule flagged it).
- Old US-rule metadata (`needs_refresh_after_close = False`, `fetch_timestamp` inside the HK session) → **stale** after the HK close. This is the migration case.
- A US holiday that is an HK trading day: the HK expected session is today's HK session; the reverse case holds too.
- US regression: fetched at 14:00 ET on a trading day → stale after 16:30 ET; fresh before.
- A calendar error → stale.
- `get_many_cached_only_fresh` / `get_cached_only_fresh` use the symbol's market key and session.
- `get_stale_intraday_symbols` returns HK symbols fetched during the HK session once the HK session has completed.
