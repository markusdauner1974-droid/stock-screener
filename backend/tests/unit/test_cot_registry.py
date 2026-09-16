from app.domain.cot.models import Participant, ReportFamily
from app.domain.cot.registry import (
    COT_INSTRUMENTS,
    dataset_for_family,
    instrument_by_slug,
)


def test_report_families_have_one_complete_dataset_definition():
    disaggregated = dataset_for_family(ReportFamily.DISAGGREGATED_FUTURES_ONLY)
    financial = dataset_for_family(ReportFamily.TFF_FUTURES_ONLY)

    assert disaggregated.dataset_id == "72hh-3qpy"
    assert disaggregated.label == "CFTC Disaggregated Futures Only"
    assert disaggregated.url.endswith("/72hh-3qpy.json")
    assert disaggregated.participant_fields[Participant.MANAGED_MONEY] == (
        "m_money_positions_long_all",
        "m_money_positions_short_all",
        "m_money_positions_spread",
    )
    assert financial.dataset_id == "gpe5-46if"
    assert financial.label == "CFTC Traders in Financial Futures - Futures Only"
    assert financial.url.endswith("/gpe5-46if.json")
    assert financial.participant_fields[Participant.LEVERAGED_FUNDS] == (
        "lev_money_positions_long",
        "lev_money_positions_short",
        "lev_money_positions_spread",
    )


def test_registry_is_the_exact_curated_universe():
    assert len(COT_INSTRUMENTS) == 31
    assert [item.category.value for item in COT_INSTRUMENTS[:10]] == [
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "rates",
        "rates",
        "rates",
    ]
    assert [item.cftc_code for item in COT_INSTRUMENTS] == [
        "13874+",
        "20974+",
        "239742",
        "244041",
        "244042",
        "240743",
        "1170E1",
        "134742",
        "134741",
        "043602",
        "067651",
        "06765T",
        "023651",
        "111659",
        "022651",
        "098662",
        "097741",
        "133741",
        "146021",
        "088691",
        "084691",
        "085692",
        "076651",
        "075651",
        "002602",
        "001602",
        "005602",
        "135731",
        "083731",
        "073732",
        "058644",
    ]
    assert instrument_by_slug("sp-500").focal_participant is Participant.LEVERAGED_FUNDS
    assert instrument_by_slug("gold").focal_participant is Participant.MANAGED_MONEY
    assert instrument_by_slug("canola").price.yahoo_symbol is None
    assert instrument_by_slug("canola").price.tradingview_url == (
        "https://www.tradingview.com/symbols/ICEUS-RS1%21/contracts/"
    )
    assert instrument_by_slug("lumber").price.yahoo_symbol == "LBR=F"
