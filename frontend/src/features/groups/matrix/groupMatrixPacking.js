import { hierarchy, pack } from 'd3-hierarchy';

export const CLUSTER_PREVIEW_LIMIT = 64;
const positiveCap = stock => Number.isFinite(stock.market_cap_usd) && stock.market_cap_usd > 0 ? stock.market_cap_usd : 0;

// Coordinates use a square 0–100 view so circles stay round at any card width.
export function packMatrixStocks(stocks, metric = 'price_change_1d') {
  const preview = stocks.slice(0, CLUSTER_PREVIEW_LIMIT);
  if (!preview.length) return [];
  const largest = Math.max(1, ...preview.map(positiveCap));
  const colorValue = stock => Number.isFinite(stock[metric]) ? stock[metric] : metric === 'rs_rating' ? 50 : 0;
  const root = hierarchy({ children: preview })
    // A 1% area floor keeps very small stocks visible; unknown caps are equal.
    .sum(stock => stock.children ? 0 : Math.max(positiveCap(stock) / largest, 0.01))
    // D3 grows the pack outward from its first circles: green, neutral, then red.
    .sort((a, b) => colorValue(b.data) - colorValue(a.data)
      || b.value - a.value || a.data.symbol.localeCompare(b.data.symbol));
  return pack().size([100, 100]).padding(0.7)(root).leaves()
    .map(node => ({ stock: node.data, x: node.x, y: node.y, r: node.r }));
}
