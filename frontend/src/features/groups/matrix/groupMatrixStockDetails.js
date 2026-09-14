import { formatCap, formatMatrixValue } from './groupMatrixColors';
import { groupLabel, sectorLabel } from './groupMatrixModel';

export function stockMetadataRows(stock, data) {
  return [
    ['Market', data.market], ['Sector', sectorLabel(stock.sector)], ['IBD industry', groupLabel(stock.ibd_industry_group)],
    ['Classification source', stock.classification_source || 'Unclassified'],
    ['Classification confidence', Number.isFinite(stock.classification_confidence) ? `${(stock.classification_confidence * 100).toFixed(0)}%` : '—'],
    ['Market cap (USD)', formatCap(stock.market_cap_usd)],
    ['1-Day Change', formatMatrixValue(stock.price_change_1d, 'price_change_1d')],
    ['1-Week Change', formatMatrixValue(stock.price_change_1w, 'price_change_1w')],
    ['1-Month Change', formatMatrixValue(stock.price_change_1m, 'price_change_1m')],
    ['Stock RS', formatMatrixValue(stock.rs_rating, 'rs_rating')],
    ['Daily data', data.as_of_date || '—'], ['Metadata read', data.metadata_read_at || '—'],
    ['Fundamentals updated', stock.fundamentals_updated_at || 'Not recorded'],
    ['Classification updated', stock.classification_updated_at || 'Not recorded'],
  ];
}
