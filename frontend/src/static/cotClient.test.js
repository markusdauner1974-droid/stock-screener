import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchStaticJson } from './dataClient';
import {
  getStaticCotHistory,
  getStaticCotIndex,
  staticCotHistoryQueryOptions,
  staticCotIndexQueryOptions,
} from './cotClient';
import {
  makeCotHistory,
  staticCotIndexFixture,
} from '../features/cot/__fixtures__/cotResponses';

vi.mock('./dataClient', () => ({ fetchStaticJson: vi.fn() }));

describe('static COT client', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches only root-manifest-advertised safe paths and slices locally', async () => {
    const fiveYear = makeCotHistory({ weekCount: 260, range: '5y' });
    fetchStaticJson
      .mockResolvedValueOnce(staticCotIndexFixture)
      .mockResolvedValueOnce(fiveYear);
    const rootManifest = { assets: { cot: { path: 'cot/index.json' } } };

    const index = await getStaticCotIndex(rootManifest);
    const history = await getStaticCotHistory(index, 'sp-500', '1y');

    expect(history.weeks).toHaveLength(52);
    expect(fetchStaticJson.mock.calls).toEqual([
      ['cot/index.json'],
      ['cot/sp-500.json'],
    ]);
  });

  it('disables unadvertised reads and keys immutable data by publication', () => {
    expect(staticCotIndexQueryOptions({ assets: {} }).enabled).toBe(false);
    const options = staticCotHistoryQueryOptions(staticCotIndexFixture, 'sp-500', '3y');
    expect(options.queryKey).toContain(7);
    expect(options.staleTime).toBe(Infinity);
    expect(() => staticCotHistoryQueryOptions(staticCotIndexFixture, 'not-listed', '1y'))
      .toThrow(/advertised/i);
  });

  it('contains no live API route', async () => {
    const module = await import('./cotClient');
    expect(Object.values(module).some((value) => String(value).includes('/api'))).toBe(false);
  });
});
