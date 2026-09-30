from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.stock import StockPrice
from app.services.stock_price_persistence import persist_stock_price_mappings

REPAIRED_DAY = date(2026, 9, 29)
LATEST_DAY = date(2026, 9, 30)


def _row(day, *, open_, high, low, close, adj_close, volume, symbol="SPY"):
    return {
        "symbol": symbol,
        "date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adj_close": adj_close,
        "volume": volume,
    }


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[StockPrice.__table__])
    return sessionmaker(bind=engine)()


def _persist(db, rows):
    result = persist_stock_price_mappings(db, {"SPY": rows})
    db.commit()
    return result


def _stored(db, day):
    return db.query(StockPrice).filter(StockPrice.symbol == "SPY", StockPrice.date == day).one()


def test_next_fetch_heals_quote_repaired_bar_but_keeps_its_adj_close():
    db = _session()
    # Bar rebuilt from the v7 quote after Yahoo's history dropped the session.
    _persist(db, [_row(REPAIRED_DAY, open_=766.83, high=766.95, low=762.35, close=764.2, adj_close=761.0, volume=36_577_604)])

    result = _persist(
        db,
        [
            # Yahoo's official bar: same close (float32 noise), different O/H/L/V.
            _row(REPAIRED_DAY, open_=766.8, high=767.0, low=762.3, close=764.2000122, adj_close=762.5, volume=37_250_900),
            _row(LATEST_DAY, open_=764.0, high=766.0, low=761.0, close=765.0, adj_close=765.0, volume=40_000_000),
        ],
    )

    healed = _stored(db, REPAIRED_DAY)
    assert result == {"inserted": 1, "updated": 1}
    assert (healed.open, healed.high, healed.low, healed.volume) == (766.8, 767.0, 762.3, 37_250_900)
    assert healed.adj_close == 761.0  # adjustment basis untouched: no splice


def test_back_adjusted_older_bar_is_not_spliced():
    db = _session()
    _persist(db, [_row(REPAIRED_DAY, open_=100.0, high=101.0, low=99.0, close=100.0, adj_close=100.0, volume=10)])

    # A 2:1 split halves the refetched history; the replacement path owns that.
    _persist(
        db,
        [
            _row(REPAIRED_DAY, open_=50.0, high=50.5, low=49.5, close=50.0, adj_close=50.0, volume=20),
            _row(LATEST_DAY, open_=51.0, high=52.0, low=50.0, close=51.0, adj_close=51.0, volume=20),
        ],
    )

    assert _stored(db, REPAIRED_DAY).close == 100.0


def test_identical_older_bar_is_not_rewritten():
    db = _session()
    bar = _row(REPAIRED_DAY, open_=766.8, high=767.0, low=762.3, close=764.2, adj_close=762.5, volume=37_250_900)
    _persist(db, [bar])

    result = _persist(
        db,
        [bar, _row(LATEST_DAY, open_=764.0, high=766.0, low=761.0, close=765.0, adj_close=765.0, volume=1)],
    )

    assert result == {"inserted": 1, "updated": 0}


def test_stock_price_declares_no_index_duplicating_the_unique_constraint():
    # #426: uix_symbol_date already indexes (symbol, date); no migration
    # creates idx_symbol_date, so create_all/autogenerate must not add it.
    assert [index.name for index in StockPrice.__table__.indexes
            if [c.name for c in index.columns] == ["symbol", "date"]] == []
