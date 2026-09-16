from app.domain.cot.models import Participant
from app.domain.cot.registry import COT_INSTRUMENTS, instrument_by_slug


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
    assert instrument_by_slug("lumber").price.yahoo_symbol == "LBR=F"
