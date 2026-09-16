import { describe, expect, it } from 'vitest';

import {
  cotCatalogQueryKey,
  cotHistoryQueryKey,
  normalizeCotCatalog,
  normalizeCotHistory,
  normalizeCotSnapshot,
  normalizeStaticCotIndex,
  sliceCotHistory,
} from './cotContract';
import {
  cotCatalogFixture,
  cotHistoryFixture,
  cotSnapshotFixture,
  makeCotHistory,
  staticCotIndexFixture,
} from './__fixtures__/cotResponses';

describe('COT contract', () => {
  it('normalizes catalog, history, snapshot, and static index', () => {
    expect(normalizeCotCatalog(cotCatalogFixture)).toBe(cotCatalogFixture);
    expect(normalizeCotHistory(cotHistoryFixture)).toBe(cotHistoryFixture);
    expect(normalizeCotSnapshot(cotSnapshotFixture)).toBe(cotSnapshotFixture);
    expect(normalizeStaticCotIndex(staticCotIndexFixture)).toBe(staticCotIndexFixture);
  });

  it('rejects an available percentile without a value', () => {
    const payload = structuredClone(cotHistoryFixture);
    payload.weeks[0].positions[0].percentile_status = 'available';
    payload.weeks[0].positions[0].percentile_3y = null;
    expect(() => normalizeCotHistory(payload)).toThrow(/percentile/i);
  });

  it('slices static five-year data without changing percentile values', () => {
    const history = makeCotHistory({ weekCount: 260, range: '5y' });
    const sliced = sliceCotHistory(history, '1y');
    expect(sliced.weeks).toHaveLength(52);
    expect(sliced.weeks.at(-1).positions[0].percentile_3y)
      .toBe(history.weeks.at(-1).positions[0].percentile_3y);
  });

  it('rejects unsafe paths, identity mismatches, duplicates, and non-finite numbers', () => {
    const unsafe = structuredClone(staticCotIndexFixture);
    unsafe.histories['sp-500'].path = '../secret.json';
    expect(() => normalizeStaticCotIndex(unsafe)).toThrow(/path/i);

    const mixed = structuredClone(staticCotIndexFixture);
    mixed.publication_id = 99;
    expect(() => normalizeStaticCotIndex(mixed)).toThrow(/publication/i);

    const duplicate = structuredClone(cotCatalogFixture);
    duplicate.instruments.push({ ...duplicate.instruments[0] });
    expect(() => normalizeCotCatalog(duplicate)).toThrow(/duplicate|order/i);

    const nonFinite = structuredClone(cotHistoryFixture);
    nonFinite.weeks[0].price_close = Infinity;
    expect(() => normalizeCotHistory(nonFinite)).toThrow(/finite/i);
  });

  it('keys reads by mode, publication, path, instrument, and range', () => {
    expect(cotCatalogQueryKey('static', 7, 'cot/index.json'))
      .toEqual(['cot', 'catalog', 'static', 7, 'cot/index.json']);
    expect(cotHistoryQueryKey({ mode: 'live', publicationId: 7, slug: 'gold', range: '1y' }))
      .not.toEqual(cotHistoryQueryKey({ mode: 'live', publicationId: 7, slug: 'gold', range: '5y' }));
  });
});
