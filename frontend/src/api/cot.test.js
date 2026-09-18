import { beforeEach, describe, expect, it, vi } from 'vitest';

import apiClient from './client';
import { getCotCatalog, getCotHistory, getCotSnapshot } from './cot';
import {
  cotCatalogFixture,
  cotHistoryFixture,
  cotSnapshotFixture,
} from '../features/cot/__fixtures__/cotResponses';

vi.mock('./client', () => ({ default: { get: vi.fn() } }));

describe('live COT client', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls only protected COT read routes and normalizes responses', async () => {
    apiClient.get
      .mockResolvedValueOnce({ data: cotCatalogFixture })
      .mockResolvedValueOnce({
        data: {
          ...cotHistoryFixture,
          range: '3y',
          slug: 'gold',
          display_name: 'Gold',
        },
      })
      .mockResolvedValueOnce({ data: cotSnapshotFixture });

    expect(await getCotCatalog()).toEqual(cotCatalogFixture);
    expect(await getCotHistory('gold', '3y', 7)).toEqual({
      ...cotHistoryFixture,
      range: '3y',
      slug: 'gold',
      display_name: 'Gold',
    });
    expect(await getCotSnapshot(7)).toEqual(cotSnapshotFixture);
    expect(apiClient.get.mock.calls).toEqual([
      ['/v1/cot/instruments'],
      ['/v1/cot/instruments/gold/history', { params: { range: '3y' } }],
      ['/v1/cot/snapshot'],
    ]);
  });
});
