"""Repair Yahoo price frames whose latest session is missing, using Yahoo's quote feed.

Yahoo's daily history for JP often lacks the last completed session for hours
after the close (on 2026-09-29, still absent for every sampled symbol nine
hours after the TSE close). Yahoo's v7 quote endpoint is a separate, current
pipeline: after the close its ``regularMarket*`` fields describe the completed
session, closing auction included (matched TradingView on 50/50 JP symbols on
2026-09-29). A quote only describes the *latest* session, so it can fill that
one session and nothing older.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .hk_sina_price_repair import repair_missing_latest_sessions, stale_symbols

logger = logging.getLogger(__name__)

YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_QUOTE_BATCH_SIZE = 100
YAHOO_QUOTE_TIMEOUT_SECONDS = 20
# Stop after this many consecutive failed requests so a block costs a few
# timeouts, not one per batch.
YAHOO_QUOTE_MAX_CONSECUTIVE_FAILURES = 3
# Sleeps before re-sending a failed batch: Yahoo's 429 bursts on CI runners
# clear within about a minute, and a lost batch drops 100 symbols' latest session.
YAHOO_QUOTE_RETRY_BACKOFF_SECONDS = (15, 45)
# ponytail: process-wide breaker because callers repair one 150-symbol batch at
# a time; after this many consecutive batches exhaust their retries, send each
# batch once until a request succeeds, so a hard block costs minutes, not hours.
_retry_breaker = {"exhausted_batches": 0}
_QUOTE_FIELDS = (
    "regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,"
    "regularMarketPrice,regularMarketVolume,regularMarketTime,marketState"
)
# The quote describes a session still in progress; never treat it as a close.
_LIVE_MARKET_STATES = {"REGULAR", "PRE"}

QuoteFetcher = Callable[[list[str]], list[dict[str, Any]]]


def fetch_yahoo_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    """Return raw v7 quote dicts for up to ~100 symbols in one request."""
    from yfinance.data import YfData  # handles Yahoo's cookie/crumb

    response = YfData().get(
        YAHOO_QUOTE_URL,
        params={"symbols": ",".join(symbols), "fields": _QUOTE_FIELDS},
        timeout=YAHOO_QUOTE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["quoteResponse"]["result"] or []


def quote_session_bar(
    quote: Mapping[str, Any], *, expected_session: date, market_tz: ZoneInfo
) -> pd.DataFrame | None:
    """One-row OHLCV frame for ``expected_session``, or None if the quote describes another session."""
    if quote.get("marketState") in _LIVE_MARKET_STATES:
        return None
    market_time = quote.get("regularMarketTime")
    if market_time is None:
        return None
    session = datetime.fromtimestamp(int(market_time), tz=timezone.utc).astimezone(market_tz).date()
    if session != expected_session:
        return None
    try:
        row = {
            "Open": float(quote["regularMarketOpen"]),
            "High": float(quote["regularMarketDayHigh"]),
            "Low": float(quote["regularMarketDayLow"]),
            "Close": float(quote["regularMarketPrice"]),
            "Volume": float(quote.get("regularMarketVolume") or 0),
        }
    except (KeyError, TypeError, ValueError):
        return None
    # Also rejects NaN (every comparison is False). Zero volume stays valid: indices report 0.
    body_low, body_high = sorted((row["Open"], row["Close"]))
    if not (0 < row["Low"] <= body_low and body_high <= row["High"]):
        return None
    return pd.DataFrame([row], index=pd.DatetimeIndex([pd.Timestamp(expected_session)], name="Date"))


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _fetch_with_retries(
    batch: list[str],
    *,
    fetch_quotes: QuoteFetcher,
    wait: Callable[[], Any] | None,
    sleep: Callable[[float], Any],
) -> list[dict[str, Any]] | None:
    """Quotes for ``batch``, or None once every attempt failed."""
    retrying = _retry_breaker["exhausted_batches"] < YAHOO_QUOTE_MAX_CONSECUTIVE_FAILURES
    backoffs = YAHOO_QUOTE_RETRY_BACKOFF_SECONDS if retrying else ()
    for attempt in range(len(backoffs) + 1):
        if attempt:
            sleep(backoffs[attempt - 1])
        try:
            if wait is not None:
                wait()
            quotes = fetch_quotes(batch)
            if not quotes:
                # Every stale symbol has Yahoo history, so an empty batch is an outage.
                raise ValueError("empty quote response")
        except Exception as exc:  # provider/network variability
            logger.warning(
                "Yahoo quote repair request failed (%d symbols, attempt %d/%d): %s",
                len(batch),
                attempt + 1,
                len(backoffs) + 1,
                exc,
            )
            continue
        _retry_breaker["exhausted_batches"] = 0
        return quotes
    _retry_breaker["exhausted_batches"] += 1
    return None


def repair_from_yahoo_quotes(
    results: Mapping[str, dict[str, Any]],
    *,
    expected_session: date,
    market_tz: ZoneInfo,
    fetch_quotes: QuoteFetcher = fetch_yahoo_quotes,
    wait: Callable[[], Any] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, int]:
    """Fill the ``expected_session`` bar from Yahoo quotes into frames lacking it.

    Only stale symbols are quoted, in batches. ``wait`` is called before each
    request (the Yahoo rate budget). A failed request is retried after each
    ``YAHOO_QUOTE_RETRY_BACKOFF_SECONDS`` sleep. Mutates ``results`` in place; see
    :func:`repair_missing_latest_sessions` for the adjusted-close handling.
    """
    stale = stale_symbols(results, expected_session=expected_session)
    bars: dict[str, pd.DataFrame] = {}
    consecutive_failures = 0
    unsent = 0
    for batch in _chunks(stale, YAHOO_QUOTE_BATCH_SIZE):
        if consecutive_failures >= YAHOO_QUOTE_MAX_CONSECUTIVE_FAILURES:
            unsent += len(batch)
            continue
        quotes = _fetch_with_retries(batch, fetch_quotes=fetch_quotes, wait=wait, sleep=sleep)
        if quotes is None:
            consecutive_failures += 1
            continue
        consecutive_failures = 0
        for quote in quotes:
            bar = quote_session_bar(quote, expected_session=expected_session, market_tz=market_tz)
            if bar is not None and quote.get("symbol"):
                bars[quote["symbol"]] = bar

    stats = repair_missing_latest_sessions(
        results,
        expected_session=expected_session,
        fetch_recent=bars.get,
        source="yahoo_quote",
        max_consecutive_failures=None,
    )
    # Symbols the request breaker never sent are skipped, not failed.
    stats["failed"] -= unsent
    stats["skipped"] = unsent
    return stats
