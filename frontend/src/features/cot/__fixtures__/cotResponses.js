const publication = {
  schema_version: 'cot-v1',
  calculation_version: 'cot-positions-v1',
  registry_version: 'cot-curated-v1',
  publication_id: 7,
  report_date: '2026-09-08',
  retrieved_at: '2026-09-11T20:45:00Z',
  stale: false,
};

const tffParticipants = [
  ['dealer_intermediary', 'Dealer/Intermediary'],
  ['asset_manager', 'Asset Manager/Institutional'],
  ['leveraged_funds', 'Leveraged Funds'],
  ['other_reportables', 'Other Reportables'],
  ['nonreportables', 'Non-reportables'],
];

const position = (participant, label, net = 100) => ({
  participant,
  label,
  long: 1000 + net,
  short: 1000,
  spreading: 0,
  net,
  delta_long: 10,
  delta_short: 0,
  delta_net: 10,
  net_pct_open_interest: 1,
  percentile_3y: 75,
  percentile_status: 'available',
});

export const cotCatalogFixture = {
  publication,
  default_slug: 'sp-500',
  categories: ['equity_volatility'],
  sources: [
    { dataset_id: '72hh-3qpy', label: 'CFTC Disaggregated Futures Only', url: 'https://example.test/disaggregated' },
    { dataset_id: 'gpe5-46if', label: 'CFTC Traders in Financial Futures', url: 'https://example.test/tff' },
  ],
  instruments: [
    {
      slug: 'sp-500',
      display_name: 'S&P 500',
      category: 'equity_volatility',
      category_order: 0,
      instrument_order: 0,
      report_family: 'tff_futures_only',
      focal_participant: 'leveraged_funds',
      participants: tffParticipants.map(([value, label]) => ({ value, label })),
      price_symbol: 'ES=F',
      price_mapping_kind: 'exact_future',
      tradingview_url: null,
    },
    {
      slug: 'nasdaq-100',
      display_name: 'Nasdaq-100',
      category: 'equity_volatility',
      category_order: 0,
      instrument_order: 1,
      report_family: 'tff_futures_only',
      focal_participant: 'leveraged_funds',
      participants: tffParticipants.map(([value, label]) => ({ value, label })),
      price_symbol: 'NQ=F',
      price_mapping_kind: 'exact_future',
      tradingview_url: null,
    },
  ],
};

export const makeCotHistory = ({ weekCount = 52, slug = 'sp-500', range = '1y' } = {}) => ({
  publication,
  range,
  slug,
  display_name: slug === 'sp-500' ? 'S&P 500' : 'Nasdaq-100',
  category: 'equity_volatility',
  report_family: 'tff_futures_only',
  source_dataset_id: 'gpe5-46if',
  focal_participant: 'leveraged_funds',
  price_symbol: slug === 'sp-500' ? 'ES=F' : 'NQ=F',
  price_mapping_kind: 'exact_future',
  price_coverage_state: 'complete',
  price_history_start: '2021-09-14',
  tradingview_url: null,
  weeks: Array.from({ length: weekCount }, (_, index) => ({
    report_date: new Date(Date.UTC(2021, 8, 14 + (index * 7))).toISOString().slice(0, 10),
    open_interest: 10000,
    price_date: new Date(Date.UTC(2021, 8, 14 + (index * 7))).toISOString().slice(0, 10),
    price_close: 100 + index,
    price_change_pct: index === 0 ? null : 1,
    positions: tffParticipants.map(([participant, label], participantIndex) => (
      position(participant, label, 100 + index + participantIndex)
    )),
  })),
});

export const cotHistoryFixture = makeCotHistory();

export const cotSnapshotFixture = {
  publication,
  rows: cotCatalogFixture.instruments.map((instrument) => ({
    slug: instrument.slug,
    display_name: instrument.display_name,
    category: instrument.category,
    instrument_order: instrument.instrument_order,
    focal_participant: 'leveraged_funds',
    focal_label: 'Leveraged Funds',
    report_date: '2026-09-08',
    long: 1100,
    short: 1000,
    net: 100,
    delta_long: 10,
    delta_short: 0,
    delta_net: 10,
    net_pct_open_interest: 1,
    percentile_3y: 75,
    percentile_status: 'available',
    net_trend: [90, 100],
    price_change_pct: 1,
    price_mapping_kind: 'exact_future',
    price_coverage_state: 'complete',
  })),
};

export const staticCotIndexFixture = {
  schema_version: 'static-cot-v1',
  registry_version: 'cot-curated-v1',
  data_schema_version: 'cot-v1',
  calculation_version: 'cot-positions-v1',
  publication_id: 7,
  report_date: '2026-09-08',
  generated_at: '2026-09-16T09:00:00Z',
  default_slug: 'sp-500',
  catalog: cotCatalogFixture,
  histories: {
    'sp-500': { path: 'cot/sp-500.json' },
    'nasdaq-100': { path: 'cot/nasdaq-100.json' },
  },
};
