from __future__ import annotations

from dataclasses import dataclass

from app.domain.cot.models import (
    Category,
    CotDatasetDefinition,
    CotDatasetId,
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

_DISAGGREGATED_PARTICIPANTS = (
    Participant.PRODUCER_MERCHANT,
    Participant.SWAP_DEALER,
    Participant.MANAGED_MONEY,
    Participant.OTHER_REPORTABLES,
    Participant.NONREPORTABLES,
)
_TFF_PARTICIPANTS = (
    Participant.DEALER_INTERMEDIARY,
    Participant.ASSET_MANAGER,
    Participant.LEVERAGED_FUNDS,
    Participant.OTHER_REPORTABLES,
    Participant.NONREPORTABLES,
)

COT_DATASETS = (
    CotDatasetDefinition(
        report_family=ReportFamily.DISAGGREGATED_FUTURES_ONLY,
        dataset_id=CotDatasetId.DISAGGREGATED_FUTURES_ONLY,
        label="CFTC Disaggregated Futures Only",
        url="https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
        participants=_DISAGGREGATED_PARTICIPANTS,
        participant_fields={
            Participant.PRODUCER_MERCHANT: (
                "prod_merc_positions_long",
                "prod_merc_positions_short",
                None,
            ),
            Participant.SWAP_DEALER: (
                "swap_positions_long_all",
                "swap__positions_short_all",
                "swap__positions_spread_all",
            ),
            Participant.MANAGED_MONEY: (
                "m_money_positions_long_all",
                "m_money_positions_short_all",
                "m_money_positions_spread",
            ),
            Participant.OTHER_REPORTABLES: (
                "other_rept_positions_long",
                "other_rept_positions_short",
                "other_rept_positions_spread",
            ),
            Participant.NONREPORTABLES: (
                "nonrept_positions_long_all",
                "nonrept_positions_short_all",
                None,
            ),
        },
    ),
    CotDatasetDefinition(
        report_family=ReportFamily.TFF_FUTURES_ONLY,
        dataset_id=CotDatasetId.TFF_FUTURES_ONLY,
        label="CFTC Traders in Financial Futures - Futures Only",
        url="https://publicreporting.cftc.gov/resource/gpe5-46if.json",
        participants=_TFF_PARTICIPANTS,
        participant_fields={
            Participant.DEALER_INTERMEDIARY: (
                "dealer_positions_long_all",
                "dealer_positions_short_all",
                "dealer_positions_spread_all",
            ),
            Participant.ASSET_MANAGER: (
                "asset_mgr_positions_long",
                "asset_mgr_positions_short",
                "asset_mgr_positions_spread",
            ),
            Participant.LEVERAGED_FUNDS: (
                "lev_money_positions_long",
                "lev_money_positions_short",
                "lev_money_positions_spread",
            ),
            Participant.OTHER_REPORTABLES: (
                "other_rept_positions_long",
                "other_rept_positions_short",
                "other_rept_positions_spread",
            ),
            Participant.NONREPORTABLES: (
                "nonrept_positions_long_all",
                "nonrept_positions_short_all",
                None,
            ),
        },
    ),
)
_DATASETS_BY_FAMILY = {item.report_family: item for item in COT_DATASETS}

_FOCAL_PARTICIPANT_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: Participant.MANAGED_MONEY,
    ReportFamily.TFF_FUTURES_ONLY: Participant.LEVERAGED_FUNDS,
}


@dataclass(frozen=True)
class CotInstrumentSpec:
    slug: str
    display_name: str
    cftc_code: str
    category: Category
    report_family: ReportFamily
    price: PriceMapping


def _spec(
    slug: str,
    display_name: str,
    cftc_code: str,
    *,
    category: Category,
    report_family: ReportFamily,
    yahoo_symbol: str | None,
    price_kind: PriceMappingKind,
    tradingview_url: str | None = None,
) -> CotInstrumentSpec:
    return CotInstrumentSpec(
        slug=slug,
        display_name=display_name,
        cftc_code=cftc_code,
        category=category,
        report_family=report_family,
        price=PriceMapping(yahoo_symbol, price_kind, tradingview_url),
    )


TFF = ReportFamily.TFF_FUTURES_ONLY
DISAGGREGATED = ReportFamily.DISAGGREGATED_FUTURES_ONLY
EXACT = PriceMappingKind.EXACT_FUTURE
ETF = PriceMappingKind.ETF_PROXY
INDEX = PriceMappingKind.INDEX_PROXY

_SPECS = (
    _spec(
        "sp-500",
        "S&P 500",
        "13874+",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="ES=F",
        price_kind=EXACT,
    ),
    _spec(
        "nasdaq-100",
        "Nasdaq-100",
        "20974+",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="NQ=F",
        price_kind=EXACT,
    ),
    _spec(
        "russell-2000",
        "Russell 2000",
        "239742",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="RTY=F",
        price_kind=EXACT,
    ),
    _spec(
        "msci-eafe",
        "MSCI EAFE",
        "244041",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="EFA",
        price_kind=ETF,
    ),
    _spec(
        "msci-em",
        "MSCI Emerging Markets",
        "244042",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="EEM",
        price_kind=ETF,
    ),
    _spec(
        "nikkei",
        "Nikkei",
        "240743",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="NKD=F",
        price_kind=EXACT,
    ),
    _spec(
        "vix",
        "VIX",
        "1170E1",
        category=Category.EQUITY_VOLATILITY,
        report_family=TFF,
        yahoo_symbol="^VIX",
        price_kind=INDEX,
    ),
    _spec(
        "sofr-1m",
        "1-Month SOFR",
        "134742",
        category=Category.RATES,
        report_family=TFF,
        yahoo_symbol="SGOV",
        price_kind=ETF,
    ),
    _spec(
        "sofr-3m",
        "3-Month SOFR",
        "134741",
        category=Category.RATES,
        report_family=TFF,
        yahoo_symbol="BIL",
        price_kind=ETF,
    ),
    _spec(
        "ust-10y",
        "US Treasury 10-Year",
        "043602",
        category=Category.RATES,
        report_family=TFF,
        yahoo_symbol="ZN=F",
        price_kind=EXACT,
    ),
    _spec(
        "wti-crude",
        "WTI Crude",
        "067651",
        category=Category.ENERGY,
        report_family=DISAGGREGATED,
        yahoo_symbol="CL=F",
        price_kind=EXACT,
    ),
    _spec(
        "brent-crude",
        "Brent Crude",
        "06765T",
        category=Category.ENERGY,
        report_family=DISAGGREGATED,
        yahoo_symbol="BZ=F",
        price_kind=EXACT,
    ),
    _spec(
        "henry-hub-natural-gas",
        "Henry Hub Natural Gas",
        "023651",
        category=Category.ENERGY,
        report_family=DISAGGREGATED,
        yahoo_symbol="NG=F",
        price_kind=EXACT,
    ),
    _spec(
        "rbob-gasoline",
        "RBOB Gasoline",
        "111659",
        category=Category.ENERGY,
        report_family=DISAGGREGATED,
        yahoo_symbol="RB=F",
        price_kind=EXACT,
    ),
    _spec(
        "ulsd-heating-oil",
        "ULSD / Heating Oil",
        "022651",
        category=Category.ENERGY,
        report_family=DISAGGREGATED,
        yahoo_symbol="HO=F",
        price_kind=EXACT,
    ),
    _spec(
        "usd-index",
        "US Dollar Index",
        "098662",
        category=Category.CURRENCIES,
        report_family=TFF,
        yahoo_symbol="DX-Y.NYB",
        price_kind=INDEX,
    ),
    _spec(
        "japanese-yen",
        "Japanese Yen",
        "097741",
        category=Category.CURRENCIES,
        report_family=TFF,
        yahoo_symbol="6J=F",
        price_kind=EXACT,
    ),
    _spec(
        "bitcoin",
        "Bitcoin",
        "133741",
        category=Category.DIGITAL_ASSETS,
        report_family=TFF,
        yahoo_symbol="BTC=F",
        price_kind=EXACT,
    ),
    _spec(
        "ether",
        "Ether",
        "146021",
        category=Category.DIGITAL_ASSETS,
        report_family=TFF,
        yahoo_symbol="ETH=F",
        price_kind=EXACT,
    ),
    _spec(
        "gold",
        "Gold",
        "088691",
        category=Category.METALS,
        report_family=DISAGGREGATED,
        yahoo_symbol="GC=F",
        price_kind=EXACT,
    ),
    _spec(
        "silver",
        "Silver",
        "084691",
        category=Category.METALS,
        report_family=DISAGGREGATED,
        yahoo_symbol="SI=F",
        price_kind=EXACT,
    ),
    _spec(
        "copper",
        "Copper",
        "085692",
        category=Category.METALS,
        report_family=DISAGGREGATED,
        yahoo_symbol="HG=F",
        price_kind=EXACT,
    ),
    _spec(
        "platinum",
        "Platinum",
        "076651",
        category=Category.METALS,
        report_family=DISAGGREGATED,
        yahoo_symbol="PL=F",
        price_kind=EXACT,
    ),
    _spec(
        "palladium",
        "Palladium",
        "075651",
        category=Category.METALS,
        report_family=DISAGGREGATED,
        yahoo_symbol="PA=F",
        price_kind=EXACT,
    ),
    _spec(
        "corn",
        "Corn",
        "002602",
        category=Category.GRAINS_OILSEEDS,
        report_family=DISAGGREGATED,
        yahoo_symbol="ZC=F",
        price_kind=EXACT,
    ),
    _spec(
        "wheat-srw",
        "Wheat",
        "001602",
        category=Category.GRAINS_OILSEEDS,
        report_family=DISAGGREGATED,
        yahoo_symbol="ZW=F",
        price_kind=EXACT,
    ),
    _spec(
        "soybeans",
        "Soybeans",
        "005602",
        category=Category.GRAINS_OILSEEDS,
        report_family=DISAGGREGATED,
        yahoo_symbol="ZS=F",
        price_kind=EXACT,
    ),
    _spec(
        "canola",
        "Canola",
        "135731",
        category=Category.GRAINS_OILSEEDS,
        report_family=DISAGGREGATED,
        yahoo_symbol=None,
        price_kind=PriceMappingKind.UNAVAILABLE,
        tradingview_url="https://www.tradingview.com/symbols/ICEUS-RS1%21/contracts/",
    ),
    _spec(
        "coffee",
        "Coffee",
        "083731",
        category=Category.SOFTS,
        report_family=DISAGGREGATED,
        yahoo_symbol="KC=F",
        price_kind=EXACT,
    ),
    _spec(
        "cocoa",
        "Cocoa",
        "073732",
        category=Category.SOFTS,
        report_family=DISAGGREGATED,
        yahoo_symbol="CC=F",
        price_kind=EXACT,
    ),
    _spec(
        "lumber",
        "Lumber",
        "058644",
        category=Category.LUMBER,
        report_family=DISAGGREGATED,
        yahoo_symbol="LBR=F",
        price_kind=EXACT,
    ),
)


def participants_for(report_family: ReportFamily) -> tuple[Participant, ...]:
    return dataset_for_family(report_family).participants


def dataset_for_family(report_family: ReportFamily) -> CotDatasetDefinition:
    return _DATASETS_BY_FAMILY[report_family]


def _build_registry() -> tuple[CotInstrumentDefinition, ...]:
    definitions: list[CotInstrumentDefinition] = []
    for instrument_order, spec in enumerate(_SPECS):
        definitions.append(
            CotInstrumentDefinition(
                slug=spec.slug,
                display_name=spec.display_name,
                cftc_code=spec.cftc_code,
                category=spec.category,
                category_order=CATEGORY_ORDER.index(spec.category),
                instrument_order=instrument_order,
                report_family=spec.report_family,
                focal_participant=_FOCAL_PARTICIPANT_BY_FAMILY[spec.report_family],
                participants=participants_for(spec.report_family),
                price=spec.price,
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
