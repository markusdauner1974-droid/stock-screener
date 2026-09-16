from __future__ import annotations

from app.domain.cot.models import (
    Category,
    CotInstrumentDefinition,
    Participant,
    PriceMapping,
    PriceMappingKind,
    ReportFamily,
)


CATEGORY_ORDER = (
    Category.EQUITY_VOLATILITY,
    Category.RATES,
    Category.ENERGY,
    Category.CURRENCIES,
    Category.DIGITAL_ASSETS,
    Category.METALS,
    Category.GRAINS_OILSEEDS,
    Category.SOFTS,
    Category.LUMBER,
)

PARTICIPANT_LABELS = {
    Participant.PRODUCER_MERCHANT: "Producer/Merchant/Processor/User",
    Participant.SWAP_DEALER: "Swap Dealer",
    Participant.MANAGED_MONEY: "Managed Money",
    Participant.DEALER_INTERMEDIARY: "Dealer/Intermediary",
    Participant.ASSET_MANAGER: "Asset Manager/Institutional",
    Participant.LEVERAGED_FUNDS: "Leveraged Funds",
    Participant.OTHER_REPORTABLES: "Other Reportables",
    Participant.NONREPORTABLES: "Non-reportables",
}

_PARTICIPANTS_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: (
        Participant.PRODUCER_MERCHANT,
        Participant.SWAP_DEALER,
        Participant.MANAGED_MONEY,
        Participant.OTHER_REPORTABLES,
        Participant.NONREPORTABLES,
    ),
    ReportFamily.TFF_FUTURES_ONLY: (
        Participant.DEALER_INTERMEDIARY,
        Participant.ASSET_MANAGER,
        Participant.LEVERAGED_FUNDS,
        Participant.OTHER_REPORTABLES,
        Participant.NONREPORTABLES,
    ),
}

_FOCAL_PARTICIPANT_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: Participant.MANAGED_MONEY,
    ReportFamily.TFF_FUTURES_ONLY: Participant.LEVERAGED_FUNDS,
}

_SPECS = (
    ("sp-500", "S&P 500", "13874+", "equity_volatility", "tff", "ES=F", "exact_future"),
    ("nasdaq-100", "Nasdaq-100", "20974+", "equity_volatility", "tff", "NQ=F", "exact_future"),
    ("russell-2000", "Russell 2000", "239742", "equity_volatility", "tff", "RTY=F", "exact_future"),
    ("msci-eafe", "MSCI EAFE", "244041", "equity_volatility", "tff", "EFA", "etf_proxy"),
    ("msci-em", "MSCI Emerging Markets", "244042", "equity_volatility", "tff", "EEM", "etf_proxy"),
    ("nikkei", "Nikkei", "240743", "equity_volatility", "tff", "NKD=F", "exact_future"),
    ("vix", "VIX", "1170E1", "equity_volatility", "tff", "^VIX", "index_proxy"),
    ("sofr-1m", "1-Month SOFR", "134742", "rates", "tff", "SGOV", "etf_proxy"),
    ("sofr-3m", "3-Month SOFR", "134741", "rates", "tff", "BIL", "etf_proxy"),
    ("ust-10y", "US Treasury 10-Year", "043602", "rates", "tff", "ZN=F", "exact_future"),
    ("wti-crude", "WTI Crude", "067651", "energy", "disaggregated", "CL=F", "exact_future"),
    ("brent-crude", "Brent Crude", "06765T", "energy", "disaggregated", "BZ=F", "exact_future"),
    ("henry-hub-natural-gas", "Henry Hub Natural Gas", "023651", "energy", "disaggregated", "NG=F", "exact_future"),
    ("rbob-gasoline", "RBOB Gasoline", "111659", "energy", "disaggregated", "RB=F", "exact_future"),
    ("ulsd-heating-oil", "ULSD / Heating Oil", "022651", "energy", "disaggregated", "HO=F", "exact_future"),
    ("usd-index", "US Dollar Index", "098662", "currencies", "tff", "DX-Y.NYB", "index_proxy"),
    ("japanese-yen", "Japanese Yen", "097741", "currencies", "tff", "6J=F", "exact_future"),
    ("bitcoin", "Bitcoin", "133741", "digital_assets", "tff", "BTC=F", "exact_future"),
    ("ether", "Ether", "146021", "digital_assets", "tff", "ETH=F", "exact_future"),
    ("gold", "Gold", "088691", "metals", "disaggregated", "GC=F", "exact_future"),
    ("silver", "Silver", "084691", "metals", "disaggregated", "SI=F", "exact_future"),
    ("copper", "Copper", "085692", "metals", "disaggregated", "HG=F", "exact_future"),
    ("platinum", "Platinum", "076651", "metals", "disaggregated", "PL=F", "exact_future"),
    ("palladium", "Palladium", "075651", "metals", "disaggregated", "PA=F", "exact_future"),
    ("corn", "Corn", "002602", "grains_oilseeds", "disaggregated", "ZC=F", "exact_future"),
    ("wheat-srw", "Wheat", "001602", "grains_oilseeds", "disaggregated", "ZW=F", "exact_future"),
    ("soybeans", "Soybeans", "005602", "grains_oilseeds", "disaggregated", "ZS=F", "exact_future"),
    ("canola", "Canola", "135731", "grains_oilseeds", "disaggregated", None, "unavailable"),
    ("coffee", "Coffee", "083731", "softs", "disaggregated", "KC=F", "exact_future"),
    ("cocoa", "Cocoa", "073732", "softs", "disaggregated", "CC=F", "exact_future"),
    ("lumber", "Lumber", "058644", "lumber", "disaggregated", "LBR=F", "exact_future"),
)

_FAMILY_BY_SHORT_NAME = {
    "disaggregated": ReportFamily.DISAGGREGATED_FUTURES_ONLY,
    "tff": ReportFamily.TFF_FUTURES_ONLY,
}


def participants_for(report_family: ReportFamily) -> tuple[Participant, ...]:
    return _PARTICIPANTS_BY_FAMILY[report_family]


def _build_registry() -> tuple[CotInstrumentDefinition, ...]:
    definitions: list[CotInstrumentDefinition] = []
    for instrument_order, spec in enumerate(_SPECS):
        slug, name, cftc_code, category_value, family_name, yahoo_symbol, kind_value = spec
        category = Category(category_value)
        report_family = _FAMILY_BY_SHORT_NAME[family_name]
        definitions.append(
            CotInstrumentDefinition(
                slug=slug,
                display_name=name,
                cftc_code=cftc_code,
                category=category,
                category_order=CATEGORY_ORDER.index(category),
                instrument_order=instrument_order,
                report_family=report_family,
                focal_participant=_FOCAL_PARTICIPANT_BY_FAMILY[report_family],
                participants=participants_for(report_family),
                price=PriceMapping(
                    yahoo_symbol=yahoo_symbol,
                    kind=PriceMappingKind(kind_value),
                    tradingview_url=(
                        "https://www.tradingview.com/symbols/ICEUS-RS1%21/contracts/"
                        if slug == "canola"
                        else None
                    ),
                ),
            )
        )
    return tuple(definitions)


COT_INSTRUMENTS = _build_registry()
_INSTRUMENTS_BY_SLUG = {item.slug: item for item in COT_INSTRUMENTS}


def instrument_by_slug(slug: str) -> CotInstrumentDefinition:
    try:
        return _INSTRUMENTS_BY_SLUG[slug]
    except KeyError as exc:
        raise KeyError(f"unknown COT instrument: {slug}") from exc
