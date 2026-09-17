const fail = (message) => {
  throw new Error(`Invalid COT contract: ${message}`);
};

export const COT_RANGES = Object.freeze({ '1y': 52, '3y': 156, '5y': 260 });
export const COT_DEFAULT_SLUG = 'sp-500';
export const COT_SCHEMA_VERSION = 'cot-v1';
export const COT_CALCULATION_VERSION = 'cot-positions-v1';
export const STATIC_COT_SCHEMA_VERSION = 'static-cot-v1';

const RANGES = new Set(Object.keys(COT_RANGES));

const requireObject = (value, location) => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(`${location} must be an object`);
  }
  return value;
};

const requirePublication = (publication) => {
  requireObject(publication, 'publication');
  if (publication.schema_version !== COT_SCHEMA_VERSION) fail('schema version mismatch');
  if (publication.calculation_version !== COT_CALCULATION_VERSION) {
    fail('calculation version mismatch');
  }
  if (!Number.isInteger(publication.publication_id) || publication.publication_id <= 0) {
    fail('publication ID must be positive');
  }
  return publication;
};

export const normalizeCotCatalog = (payload) => {
  requireObject(payload, 'catalog');
  requirePublication(payload.publication);
  if (payload.default_slug !== COT_DEFAULT_SLUG) fail('default slug mismatch');
  return payload;
};

export const normalizeCotHistory = (payload, context = {}) => {
  requireObject(payload, 'history');
  requirePublication(payload.publication);
  if (!RANGES.has(payload.range)) fail('unknown range');
  if (context.expectedRange && payload.range !== context.expectedRange) {
    fail('range identity mismatch');
  }
  if (context.expectedSlug && payload.slug !== context.expectedSlug) {
    fail('instrument identity mismatch');
  }
  if (
    context.expectedPublicationId !== undefined
    && payload.publication.publication_id !== context.expectedPublicationId
  ) {
    fail('publication identity mismatch');
  }
  return payload;
};

export const normalizeCotSnapshot = (payload) => {
  requireObject(payload, 'snapshot');
  requirePublication(payload.publication);
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
  requireObject(payload, 'static index');
  if (payload.schema_version !== STATIC_COT_SCHEMA_VERSION) fail('static schema version mismatch');
  if (payload.data_schema_version !== COT_SCHEMA_VERSION) fail('data schema version mismatch');
  if (payload.calculation_version !== COT_CALCULATION_VERSION) {
    fail('calculation version mismatch');
  }

  const catalog = normalizeCotCatalog(payload.catalog);
  if (
    payload.publication_id !== catalog.publication.publication_id
    || payload.report_date !== catalog.publication.report_date
    || payload.data_schema_version !== catalog.publication.schema_version
    || payload.calculation_version !== catalog.publication.calculation_version
  ) fail('publication identity mismatch');
  if (payload.default_slug !== catalog.default_slug) fail('default slug identity mismatch');

  const histories = requireObject(payload.histories, 'static index histories');
  const slugs = catalog.instruments.map((item) => item.slug);
  if (Object.keys(histories).length !== slugs.length || slugs.some((slug) => !(slug in histories))) {
    fail('history coverage does not match catalog');
  }
  slugs.forEach((slug) => {
    const path = requireSafeCotPath(histories[slug]?.path, `histories.${slug}.path`);
    if (path !== `cot/${slug}.json`) fail(`history path identity mismatch: ${slug}`);
  });
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
