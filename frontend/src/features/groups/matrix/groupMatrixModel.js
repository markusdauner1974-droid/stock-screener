export const DEFAULT_MATRIX_PREFERENCES = {
  layout: 'grid', metric: 'price_change_1d',
  tiers: ['large_mega', 'mid', 'small', 'micro', 'nano', 'unknown'],
};
export const sectorLabel = value => value || 'Unknown sector';
export const groupLabel = value => value || 'Unclassified IBD';
const nameOrder = (a, b) => a === b ? 0 : !a ? 1 : !b ? -1 : a.localeCompare(b);
const stockOrder = (a, b) => (b.market_cap_usd || 0) - (a.market_cap_usd || 0) || a.symbol.localeCompare(b.symbol);

export function buildMatrixModel(source, { sector, group, tiers, search }) {
  if (new Set(source.map(s => s.symbol)).size !== source.length) throw new Error('Duplicate Matrix symbol');
  const query = search.trim().toLowerCase();
  const stocks = source.filter(s => (!sector || sectorLabel(s.sector) === sector)
    && (!group || groupLabel(s.ibd_industry_group) === group)
    && tiers.includes(s.cap_tier)
    && (!query || `${s.symbol} ${s.company_name || ''}`.toLowerCase().includes(query)));
  const groups = new Map();
  for (const stock of stocks) {
    const key = JSON.stringify([stock.sector, stock.ibd_industry_group]);
    if (!groups.has(key)) groups.set(key, { key, kind: 'group', sector: stock.sector,
      group: stock.ibd_industry_group, stocks: [], stocksByTier: {} });
    const row = groups.get(key);
    row.stocks.push(stock);
    (row.stocksByTier[stock.cap_tier] ||= []).push(stock);
  }
  const rows = [...groups.values()].sort((a, b) => nameOrder(a.sector, b.sector) || nameOrder(a.group, b.group));
  const gridRows = [];
  const clustersByTier = Object.fromEntries(tiers.map(t => [t, []]));
  for (const row of rows) {
    row.stocks.sort(stockOrder);
    Object.values(row.stocksByTier).forEach(list => list.sort(stockOrder));
    if (!gridRows.length || gridRows.at(-1).sector !== row.sector) {
      gridRows.push({ kind: 'sector', key: `sector:${row.sector}`, sector: row.sector });
    }
    gridRows.push(row);
    for (const tier of tiers) {
      const list = row.stocksByTier[tier];
      if (!list?.length) continue;
      const cards = clustersByTier[tier];
      if (!cards.length || cards.at(-1).sector !== row.sector) {
        cards.push({ kind: 'sector', key: `sector:${row.sector}`, sector: row.sector });
      }
      cards.push({ ...row, stocks: list });
    }
  }
  return { stocks, gridRows, clustersByTier, stockCount: stocks.length,
    sectors: [...new Set(stocks.map(s => s.sector))].sort(nameOrder) };
}
