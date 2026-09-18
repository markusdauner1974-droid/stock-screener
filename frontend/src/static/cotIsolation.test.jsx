import { afterEach, describe, expect, it, vi } from 'vitest';

import { getStaticCotHistory, getStaticCotIndex } from './cotClient';
import {
  makeCotHistory,
  staticCotIndexFixture,
} from '../features/cot/__fixtures__/cotResponses';

describe('static COT external-call isolation', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses safe static-data URLs for the index and two instruments', async () => {
    const responses = [
      staticCotIndexFixture,
      makeCotHistory({ weekCount: 260, range: '5y' }),
      makeCotHistory({ weekCount: 260, range: '5y', slug: 'nasdaq-100' }),
    ];
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => responses.shift(),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const index = await getStaticCotIndex({ assets: { cot: { path: 'cot/index.json' } } });
    await getStaticCotHistory(index, 'sp-500', '1y');
    await getStaticCotHistory(index, 'nasdaq-100', '3y');

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      '/static-data/cot/index.json',
      '/static-data/cot/sp-500.json',
      '/static-data/cot/nasdaq-100.json',
    ]);
    urls.forEach((url) => {
      expect(url).not.toMatch(/\/api|cftc\.gov|finance\.yahoo|tradingview\.com/i);
    });
  });
});
