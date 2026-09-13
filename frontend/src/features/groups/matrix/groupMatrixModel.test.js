import { describe, expect, it } from 'vitest';
import { buildMatrixModel } from './groupMatrixModel';
import { matrixColor, formatMatrixValue } from './groupMatrixColors';

const stocks = [
  { symbol: 'A', company_name: 'Alpha', sector: 'Tech', ibd_industry_group: 'Software', cap_tier: 'mid', market_cap_usd: 3e9 },
  { symbol: 'B', company_name: 'Beta', sector: 'Finance', ibd_industry_group: 'Software', cap_tier: 'small', market_cap_usd: 5e8 },
  { symbol: 'C', company_name: 'Charlie', sector: null, ibd_industry_group: null, cap_tier: 'unknown', market_cap_usd: null },
];
const filters = { sector: '', group: '', tiers: ['mid', 'small', 'unknown'], search: '' };
it('intersects filters and matches company names case insensitively', () => {
  expect(buildMatrixModel(stocks, { ...filters, search: 'ALPH' }).stocks.map(s => s.symbol)).toEqual(['A']);
  expect(buildMatrixModel(stocks, { ...filters, sector: 'Tech', tiers: ['small'] }).stockCount).toBe(0);
  expect(buildMatrixModel(stocks, { ...filters, tiers: [] }).stockCount).toBe(0);
});
it('both layouts retain each stock once including unknown classifications', () => {
  const model = buildMatrixModel(stocks, filters);
  expect(model.gridRows.filter(r => r.kind === 'group')).toHaveLength(3);
  expect(Object.values(model.clustersByTier).flat().filter(r => r.kind === 'group').flatMap(r => r.stocks).map(s => s.symbol).sort()).toEqual(['A','B','C']);
});
it('orders stocks by cap then symbol and rejects duplicate symbols', () => {
  const model = buildMatrixModel([...stocks, { ...stocks[0], symbol: 'D', market_cap_usd: 4e9 }], filters);
  expect(model.gridRows.find(r => r.sector === 'Tech' && r.kind === 'group').stocks.map(s => s.symbol)).toEqual(['D', 'A']);
  expect(() => buildMatrixModel([stocks[0], stocks[0]], filters)).toThrow();
});
describe('color semantics', () => {
  const theme = { palette: { mode: 'dark', text: { primary: '#fff' } } };
  it('separates missing from zero, clips color but not text', () => {
    expect(matrixColor(null, 'price_change_1d', theme).missing).toBe(true);
    expect(matrixColor(0, 'price_change_1d', theme).missing).toBe(false);
    expect(matrixColor(30, 'price_change_1d', theme)).toEqual(matrixColor(3, 'price_change_1d', theme));
    expect(formatMatrixValue(30, 'price_change_1d')).toBe('+30.00%');
    expect(formatMatrixValue(0, 'price_change_1d')).toBe('0.00%');
    expect(formatMatrixValue(null, 'rs_rating')).toBe('—');
  });
  it('uses stock RS thresholds', () => {
    expect(matrixColor(80, 'rs_rating', theme).backgroundColor).not.toBe(matrixColor(70, 'rs_rating', theme).backgroundColor);
    expect(matrixColor(20, 'rs_rating', theme).backgroundColor).not.toBe(matrixColor(30, 'rs_rating', theme).backgroundColor);
  });
});
