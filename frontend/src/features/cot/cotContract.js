const fail = (message) => {
  throw new Error(`Invalid COT contract: ${message}`);
};

export const COT_RANGES = Object.freeze({ '1y': 52, '3y': 156, '5y': 260 });
export const COT_DEFAULT_SLUG = 'sp-500';
export const COT_SCHEMA_VERSION = 'cot-v1';
export const COT_CALCULATION_VERSION = 'cot-positions-v1';
export const STATIC_COT_SCHEMA_VERSION = 'static-cot-v1';

const PARTICIPANT_LABELS = Object.freeze({
  producer_merchant: 'Producer/Merchant/Processor/User',
  swap_dealer: 'Swap Dealer',
  managed_money: 'Managed Money',
  dealer_intermediary: 'Dealer/Intermediary',
  asset_manager: 'Asset Manager/Institutional',
  leveraged_funds: 'Leveraged Funds',
  other_reportables: 'Other Reportables',
  nonreportables: 'Non-reportables',
});

const RANGES = new Set(Object.keys(COT_RANGES));
const REPORT_FAMILIES = new Set(['disaggregated_futures_only', 'tff_futures_only']);
const PRICE_KINDS = new Set(['exact_future', 'etf_proxy', 'index_proxy', 'unavailable']);
const PRICE_COVERAGE = new Set(['complete', 'partial', 'unavailable']);
const PERCENTILE_STATES = new Set(['available', 'insufficient_history']);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const object = (value, location) => {
  if (!isObject(value)) fail(`${location} must be an object`);
};
const array = (value, location) => {
  if (!Array.isArray(value)) fail(`${location} must be an array`);
};
const string = (value, location, { nullable = false } = {}) => {
  if (nullable && value === null) return;
  if (typeof value !== 'string' || !value) fail(`${location} must be a non-empty string`);
};
const integer = (value, location, { nonnegative = false } = {}) => {
  if (!Number.isInteger(value) || (nonnegative && value < 0)) fail(`${location} must be an integer`);
};
const numberOrNull = (value, location) => {
  if (value !== null && (typeof value !== 'number' || !Number.isFinite(value))) {
    fail(`${location} must be a finite number or null`);
  }
};
const date = (value, location, { nullable = false } = {}) => {
  if (nullable && value === null) return;
  if (typeof value !== 'string' || !DATE_RE.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    fail(`${location} must be an ISO date`);
  }
};
const exactKeys = (value, keys, location) => {
  object(value, location);
  const expected = new Set(keys);
  const unexpected = Object.keys(value).filter((key) => !expected.has(key));
  const missing = keys.filter((key) => !(key in value));
  if (unexpected.length || missing.length) {
    fail(`${location} fields mismatch${unexpected.length ? `; unexpected ${unexpected.join(', ')}` : ''}${missing.length ? `; missing ${missing.join(', ')}` : ''}`);
  }
};
const unique = (values, location) => {
  if (new Set(values).size !== values.length) fail(`duplicate ${location}`);
};

const rejectNonFiniteNumbers = (value) => {
  if (typeof value === 'number' && !Number.isFinite(value)) fail('non-finite number');
  if (Array.isArray(value)) value.forEach(rejectNonFiniteNumbers);
  else if (isObject(value)) Object.values(value).forEach(rejectNonFiniteNumbers);
};

const validatePublication = (publication) => {
  exactKeys(publication, [
    'schema_version', 'calculation_version', 'registry_version', 'publication_id',
    'report_date', 'retrieved_at', 'stale',
  ], 'publication');
  if (publication.schema_version !== COT_SCHEMA_VERSION) fail('schema version mismatch');
  if (publication.calculation_version !== COT_CALCULATION_VERSION) fail('calculation version mismatch');
  string(publication.registry_version, 'publication.registry_version');
  integer(publication.publication_id, 'publication.publication_id');
  if (publication.publication_id <= 0) fail('publication ID must be positive');
  date(publication.report_date, 'publication.report_date');
  if (typeof publication.retrieved_at !== 'string' || Number.isNaN(Date.parse(publication.retrieved_at))) {
    fail('publication.retrieved_at must be an ISO timestamp');
  }
  if (typeof publication.stale !== 'boolean') fail('publication.stale must be a boolean');
};

const validateParticipantMetadata = (item, location) => {
  exactKeys(item, ['value', 'label'], location);
  if (!PARTICIPANT_LABELS[item.value]) fail(`${location} has unknown participant`);
  if (PARTICIPANT_LABELS[item.value] !== item.label) fail(`${location} participant label mismatch`);
};

const validateInstrument = (item, location) => {
  exactKeys(item, [
    'slug', 'display_name', 'category', 'category_order', 'instrument_order',
    'report_family', 'focal_participant', 'participants', 'price_symbol',
    'price_mapping_kind', 'tradingview_url',
  ], location);
  ['slug', 'display_name', 'category'].forEach((field) => string(item[field], `${location}.${field}`));
  integer(item.category_order, `${location}.category_order`, { nonnegative: true });
  integer(item.instrument_order, `${location}.instrument_order`, { nonnegative: true });
  if (!REPORT_FAMILIES.has(item.report_family)) fail(`${location} report family is unknown`);
  if (!PARTICIPANT_LABELS[item.focal_participant]) fail(`${location} focal participant is unknown`);
  array(item.participants, `${location}.participants`);
  item.participants.forEach((participant, index) => validateParticipantMetadata(participant, `${location}.participants[${index}]`));
  const values = item.participants.map((participant) => participant.value);
  unique(values, `${location} participant`);
  if (!values.includes(item.focal_participant)) fail(`${location} focal participant is absent`);
  if (!PRICE_KINDS.has(item.price_mapping_kind)) fail(`${location} price mapping kind is unknown`);
  string(item.price_symbol, `${location}.price_symbol`, { nullable: true });
  string(item.tradingview_url, `${location}.tradingview_url`, { nullable: true });
  if ((item.price_mapping_kind === 'unavailable') !== (item.price_symbol === null)) {
    fail(`${location} price mapping availability mismatch`);
  }
};

export const normalizeCotCatalog = (payload) => {
  rejectNonFiniteNumbers(payload);
  exactKeys(payload, ['publication', 'default_slug', 'categories', 'sources', 'instruments'], 'catalog');
  validatePublication(payload.publication);
  if (payload.default_slug !== COT_DEFAULT_SLUG) fail('default slug mismatch');
  array(payload.categories, 'catalog.categories');
  payload.categories.forEach((category, index) => string(category, `catalog.categories[${index}]`));
  unique(payload.categories, 'category');
  array(payload.sources, 'catalog.sources');
  payload.sources.forEach((source, index) => {
    exactKeys(source, ['dataset_id', 'label', 'url'], `catalog.sources[${index}]`);
    if (!['72hh-3qpy', 'gpe5-46if'].includes(source.dataset_id)) fail('unknown CFTC dataset');
    string(source.label, `catalog.sources[${index}].label`);
    string(source.url, `catalog.sources[${index}].url`);
  });
  unique(payload.sources.map((source) => source.dataset_id), 'source dataset');
  array(payload.instruments, 'catalog.instruments');
  payload.instruments.forEach((item, index) => validateInstrument(item, `catalog.instruments[${index}]`));
  unique(payload.instruments.map((item) => item.slug), 'instrument slug');
  const orders = payload.instruments.map((item) => item.instrument_order);
  unique(orders, 'instrument order');
  if (orders.some((order, index) => index > 0 && order <= orders[index - 1])) fail('instrument order is not curated');
  if (!payload.instruments.some((item) => item.slug === payload.default_slug)) fail('default instrument is absent');
  return payload;
};

const validatePosition = (position, location) => {
  exactKeys(position, [
    'participant', 'label', 'long', 'short', 'spreading', 'net', 'delta_long',
    'delta_short', 'delta_net', 'net_pct_open_interest', 'percentile_3y',
    'percentile_status',
  ], location);
  if (!PARTICIPANT_LABELS[position.participant]) fail(`${location} has unknown participant`);
  if (PARTICIPANT_LABELS[position.participant] !== position.label) fail(`${location} participant label mismatch`);
  ['long', 'short', 'spreading'].forEach((field) => integer(position[field], `${location}.${field}`, { nonnegative: true }));
  integer(position.net, `${location}.net`);
  if (position.net !== position.long - position.short) fail(`${location} net does not equal long minus short`);
  ['delta_long', 'delta_short', 'delta_net'].forEach((field) => {
    if (position[field] !== null) integer(position[field], `${location}.${field}`);
  });
  numberOrNull(position.net_pct_open_interest, `${location}.net_pct_open_interest`);
  numberOrNull(position.percentile_3y, `${location}.percentile_3y`);
  if (!PERCENTILE_STATES.has(position.percentile_status)) fail(`${location} percentile status is unknown`);
  if ((position.percentile_status === 'available') !== (position.percentile_3y !== null)) {
    fail(`${location} percentile availability mismatch`);
  }
  if (position.percentile_3y !== null && (position.percentile_3y < 0 || position.percentile_3y > 100)) {
    fail(`${location} percentile must be between 0 and 100`);
  }
};

export const normalizeCotHistory = (payload, context = {}) => {
  rejectNonFiniteNumbers(payload);
  exactKeys(payload, [
    'publication', 'range', 'slug', 'display_name', 'category', 'report_family',
    'source_dataset_id', 'focal_participant', 'price_symbol', 'price_mapping_kind',
    'price_coverage_state', 'price_history_start', 'tradingview_url', 'weeks',
  ], 'history');
  validatePublication(payload.publication);
  if (!RANGES.has(payload.range)) fail('unknown range');
  if (context.expectedRange && payload.range !== context.expectedRange) fail('range identity mismatch');
  if (context.expectedSlug && payload.slug !== context.expectedSlug) fail('instrument identity mismatch');
  if (context.expectedPublicationId && payload.publication.publication_id !== context.expectedPublicationId) fail('publication identity mismatch');
  ['slug', 'display_name', 'category'].forEach((field) => string(payload[field], `history.${field}`));
  if (!REPORT_FAMILIES.has(payload.report_family)) fail('unknown report family');
  if (!['72hh-3qpy', 'gpe5-46if'].includes(payload.source_dataset_id)) fail('unknown source dataset');
  if (!PARTICIPANT_LABELS[payload.focal_participant]) fail('unknown focal participant');
  if (!PRICE_KINDS.has(payload.price_mapping_kind)) fail('unknown price mapping kind');
  if (!PRICE_COVERAGE.has(payload.price_coverage_state)) fail('unknown price coverage state');
  string(payload.price_symbol, 'history.price_symbol', { nullable: true });
  date(payload.price_history_start, 'history.price_history_start', { nullable: true });
  string(payload.tradingview_url, 'history.tradingview_url', { nullable: true });
  array(payload.weeks, 'history.weeks');
  payload.weeks.forEach((week, weekIndex) => {
    const location = `history.weeks[${weekIndex}]`;
    exactKeys(week, ['report_date', 'open_interest', 'price_date', 'price_close', 'price_change_pct', 'positions'], location);
    date(week.report_date, `${location}.report_date`);
    integer(week.open_interest, `${location}.open_interest`, { nonnegative: true });
    date(week.price_date, `${location}.price_date`, { nullable: true });
    numberOrNull(week.price_close, `${location}.price_close`);
    numberOrNull(week.price_change_pct, `${location}.price_change_pct`);
    if ((week.price_date === null) !== (week.price_close === null)) fail(`${location} price availability mismatch`);
    if (week.price_date !== null && week.price_date > week.report_date) fail(`${location} price date follows report date`);
    array(week.positions, `${location}.positions`);
    week.positions.forEach((position, index) => validatePosition(position, `${location}.positions[${index}]`));
    unique(week.positions.map((position) => position.participant), `${location} participant`);
    if (!week.positions.some((position) => position.participant === payload.focal_participant)) fail(`${location} focal participant is absent`);
  });
  const dates = payload.weeks.map((week) => week.report_date);
  unique(dates, 'report date');
  if (dates.some((value, index) => index > 0 && value <= dates[index - 1])) fail('report dates are not ascending');
  const prices = payload.weeks.filter((week) => week.price_close !== null).length;
  if (payload.price_coverage_state === 'unavailable' && prices !== 0) fail('price coverage mismatch');
  if (payload.price_coverage_state === 'complete' && prices !== payload.weeks.length) fail('price coverage mismatch');
  if (payload.price_mapping_kind === 'unavailable' && payload.price_symbol !== null) fail('price mapping mismatch');
  return payload;
};

export const normalizeCotSnapshot = (payload) => {
  rejectNonFiniteNumbers(payload);
  exactKeys(payload, ['publication', 'rows'], 'snapshot');
  validatePublication(payload.publication);
  array(payload.rows, 'snapshot.rows');
  payload.rows.forEach((row, index) => {
    const location = `snapshot.rows[${index}]`;
    exactKeys(row, [
      'slug', 'display_name', 'category', 'instrument_order', 'focal_participant',
      'focal_label', 'report_date', 'long', 'short', 'net', 'delta_long',
      'delta_short', 'delta_net', 'net_pct_open_interest', 'percentile_3y',
      'percentile_status', 'net_trend', 'price_change_pct', 'price_mapping_kind',
      'price_coverage_state',
    ], location);
    ['slug', 'display_name', 'category'].forEach((field) => string(row[field], `${location}.${field}`));
    integer(row.instrument_order, `${location}.instrument_order`, { nonnegative: true });
    date(row.report_date, `${location}.report_date`);
    validatePosition({
      participant: row.focal_participant,
      label: row.focal_label,
      long: row.long,
      short: row.short,
      spreading: 0,
      net: row.net,
      delta_long: row.delta_long,
      delta_short: row.delta_short,
      delta_net: row.delta_net,
      net_pct_open_interest: row.net_pct_open_interest,
      percentile_3y: row.percentile_3y,
      percentile_status: row.percentile_status,
    }, location);
    array(row.net_trend, `${location}.net_trend`);
    if (row.net_trend.length > 12) fail(`${location}.net_trend is too long`);
    row.net_trend.forEach((value, trendIndex) => integer(value, `${location}.net_trend[${trendIndex}]`));
    numberOrNull(row.price_change_pct, `${location}.price_change_pct`);
    if (!PRICE_KINDS.has(row.price_mapping_kind) || !PRICE_COVERAGE.has(row.price_coverage_state)) fail(`${location} price state is unknown`);
  });
  unique(payload.rows.map((row) => row.slug), 'snapshot slug');
  const orders = payload.rows.map((row) => row.instrument_order);
  unique(orders, 'snapshot order');
  if (orders.some((order, index) => index > 0 && order <= orders[index - 1])) fail('snapshot order is not curated');
  return payload;
};

export const requireSafeCotPath = (path, location = 'path') => {
  if (typeof path !== 'string') fail(`unsafe ${location}`);
  const segments = path.split('/');
  if (
    path.startsWith('/') || path.includes('\\') || path.includes('://')
    || segments[0] !== 'cot'
    || segments.some((segment) => segment === '' || segment === '.' || segment === '..')
  ) fail(`unsafe ${location}`);
  return path;
};

export const normalizeStaticCotIndex = (payload) => {
  rejectNonFiniteNumbers(payload);
  exactKeys(payload, [
    'schema_version', 'data_schema_version', 'calculation_version', 'publication_id',
    'report_date', 'generated_at', 'default_slug', 'catalog', 'histories',
  ], 'static index');
  if (payload.schema_version !== STATIC_COT_SCHEMA_VERSION) fail('static schema version mismatch');
  if (payload.data_schema_version !== COT_SCHEMA_VERSION) fail('data schema version mismatch');
  if (payload.calculation_version !== COT_CALCULATION_VERSION) fail('calculation version mismatch');
  integer(payload.publication_id, 'static index publication ID');
  date(payload.report_date, 'static index report date');
  if (typeof payload.generated_at !== 'string' || Number.isNaN(Date.parse(payload.generated_at))) fail('invalid generated timestamp');
  const catalog = normalizeCotCatalog(payload.catalog);
  if (
    payload.publication_id !== catalog.publication.publication_id
    || payload.report_date !== catalog.publication.report_date
    || payload.data_schema_version !== catalog.publication.schema_version
    || payload.calculation_version !== catalog.publication.calculation_version
  ) fail('publication identity mismatch');
  if (payload.default_slug !== catalog.default_slug) fail('default slug identity mismatch');
  object(payload.histories, 'static index histories');
  const slugs = catalog.instruments.map((item) => item.slug);
  if (Object.keys(payload.histories).length !== slugs.length || slugs.some((slug) => !(slug in payload.histories))) {
    fail('history coverage does not match catalog');
  }
  const paths = [];
  slugs.forEach((slug) => {
    const entry = payload.histories[slug];
    exactKeys(entry, ['path'], `histories.${slug}`);
    requireSafeCotPath(entry.path, `histories.${slug}.path`);
    if (entry.path !== `cot/${slug}.json`) fail(`history path identity mismatch: ${slug}`);
    paths.push(entry.path);
  });
  unique(paths, 'history path');
  return payload;
};

export const sliceCotHistory = (history, range) => {
  if (!RANGES.has(range)) fail('unknown range');
  const normalized = normalizeCotHistory(history);
  return { ...normalized, range, weeks: normalized.weeks.slice(-COT_RANGES[range]) };
};

export const cotCatalogQueryKey = (mode, publicationId = null, path = null) => [
  'cot', 'catalog', mode, publicationId, path,
];

export const cotHistoryQueryKey = ({ mode, publicationId, slug, range, path = null }) => [
  'cot', 'history', mode, publicationId, slug, range, path,
];

export const cotSnapshotQueryKey = (publicationId = null) => [
  'cot', 'snapshot', 'live', publicationId,
];
