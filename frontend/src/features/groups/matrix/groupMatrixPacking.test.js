import { describe, expect, it } from 'vitest';
import { packMatrixStocks } from './groupMatrixPacking';

describe('Matrix bubble packing', () => {
  it('keeps unknown or invalid caps visible and equal-sized', () => {
    const stocks = [null, 0, -1, NaN, Infinity].map((market_cap_usd, i) => ({symbol:`S${i}`, market_cap_usd}));
    const bubbles = packMatrixStocks(stocks);
    expect(bubbles).toHaveLength(5);
    expect(bubbles.every(bubble => Number.isFinite(bubble.r) && bubble.r > 0)).toBe(true);
    expect(new Set(bubbles.map(bubble => bubble.r)).size).toBe(1);
    expect(packMatrixStocks([])).toEqual([]);
  });

  it('keeps a dense preview inside its circle without overlaps or payload mutation', () => {
    const stocks = Array.from({length:100}, (_, i) => ({symbol:`S${i}`, market_cap_usd:1e10 / (i + 1)}));
    const original = structuredClone(stocks);
    const bubbles = packMatrixStocks(stocks);
    expect(bubbles).toHaveLength(64);
    for (const [index, bubble] of bubbles.entries()) {
      expect(Math.hypot(bubble.x - 50, bubble.y - 50) + bubble.r).toBeLessThanOrEqual(50);
      for (const other of bubbles.slice(index + 1)) {
        expect(Math.hypot(bubble.x - other.x, bubble.y - other.y)).toBeGreaterThanOrEqual(bubble.r + other.r);
      }
    }
    expect(stocks).toEqual(original);
    expect(packMatrixStocks(stocks)).toEqual(bubbles);
  });
});
