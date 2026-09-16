const PRICE_KIND_LABELS = Object.freeze({
  exact_future: 'Exact future',
  etf_proxy: 'ETF proxy',
  index_proxy: 'Index proxy',
  unavailable: 'Price unavailable',
});

export const formatCotNumber = (value) => (
  value === null || value === undefined ? '—' : new Intl.NumberFormat('en-US').format(value)
);

export const formatCotPercent = (value, digits = 1) => (
  value === null || value === undefined ? '—' : `${Number(value).toFixed(digits)}%`
);

export const priceStateLabel = (kind, coverage) => {
  if (kind === 'unavailable' || coverage === 'unavailable') return 'Price unavailable';
  const base = PRICE_KIND_LABELS[kind] || 'Price context';
  return coverage === 'partial' ? `${base} · Partial price history` : base;
};

export const buildCotChartRows = (history, { mode = 'net', participant = null } = {}) => (
  (history?.weeks || []).map((week) => {
    const positions = Object.fromEntries(week.positions.map((position) => [position.participant, position]));
    const row = {
      reportDate: week.report_date,
      openInterest: week.open_interest,
      price: week.price_close,
      priceDate: week.price_date,
      priceChangePct: week.price_change_pct,
      positions,
    };
    if (mode === 'long_short') {
      const selected = positions[participant] || null;
      return {
        ...row,
        long: selected?.long ?? null,
        short: selected ? -selected.short : null,
      };
    }
    week.positions.forEach((position) => {
      row[position.participant] = position.net;
    });
    return row;
  })
);

export const latestFocalSummary = (catalog, history) => {
  if (!catalog || !history?.weeks?.length) return null;
  const instrument = catalog.instruments.find((item) => item.slug === history.slug);
  const latest = history.weeks.at(-1);
  const focalParticipant = instrument?.focal_participant || history.focal_participant;
  const focal = latest.positions.find((position) => position.participant === focalParticipant);
  if (!focal) return null;
  return {
    focalParticipant,
    focalLabel: focal.label,
    reportDate: latest.report_date,
    long: focal.long,
    short: focal.short,
    net: focal.net,
    percentile3y: focal.percentile_3y,
    percentileStatus: focal.percentile_status,
    priceChangePct: latest.price_change_pct,
    priceMappingKind: history.price_mapping_kind,
    priceCoverageState: history.price_coverage_state,
  };
};

export const cotRangeLabel = (range) => ({ '1y': '52', '3y': '156', '5y': '260' }[range] || 'available');
