import { describe, expect, it } from 'vitest';
import { packMatrixStocks } from './groupMatrixPacking';

describe('Matrix bubble packing', () => {
  it.each(['price_change_1d', 'rs_rating'])('places green, neutral and red zones from center outward for %s', metric => {
    const stocks = Array.from({length:64}, (_, i) => ({
      symbol:`S${i}`, market_cap_usd:1e10 * (1 + i % 7),
      price_change_1d:i < 60 ? [-3, 0, 3][i % 3] : null,
      rs_rating:i < 60 ? [90, 50, 10][i % 3] : null,
    }));
    const bubbles = packMatrixStocks(stocks, metric);
    const meanDistance = predicate => {
      const selected = bubbles.filter(bubble => predicate(bubble.stock[metric]));
      return selected.reduce((sum, bubble) => sum + Math.hypot(bubble.x - 50, bubble.y - 50), 0) / selected.length;
    };
    const green = meanDistance(value => value !== null && value > (metric === 'rs_rating' ? 70 : 0));
    const red = meanDistance(value => value !== null && value < (metric === 'rs_rating' ? 30 : 0));
    const neutral = meanDistance(value => value === (metric === 'rs_rating' ? 50 : 0));
    const missing = meanDistance(value => value === null);
    expect(green).toBeLessThan(neutral);
    expect(neutral).toBeLessThan(red);
    expect(missing).toBeGreaterThan(green);
    expect(missing).toBeLessThan(red);
  });

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
