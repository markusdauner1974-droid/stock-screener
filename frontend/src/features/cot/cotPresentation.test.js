import { describe, expect, it } from 'vitest';

import {
  buildCotChartRows,
  formatCotNumber,
  latestFocalSummary,
} from './cotPresentation';
import {
  cotCatalogFixture,
  cotHistoryFixture,
} from './__fixtures__/cotResponses';

describe('COT presentation helpers', () => {
  it('builds net series for every participant', () => {
    const rows = buildCotChartRows(cotHistoryFixture, { mode: 'net', participant: null });
    expect(rows.at(-1)).toMatchObject({
      leveraged_funds: 153,
      dealer_intermediary: 151,
      price: 151,
    });
  });

  it('renders selected long above zero and short below zero', () => {
    const rows = buildCotChartRows(cotHistoryFixture, {
      mode: 'long_short',
      participant: 'leveraged_funds',
    });
    expect(rows.at(-1)).toMatchObject({ long: 1153, short: -1000 });
  });

  it('resolves the instrument focal participant and never turns null into zero', () => {
    const summary = latestFocalSummary(cotCatalogFixture, cotHistoryFixture);
    expect(summary.focalLabel).toBe('Leveraged Funds');
    expect(summary.net).toBe(153);
    expect(formatCotNumber(null)).toBe('—');
  });
});
