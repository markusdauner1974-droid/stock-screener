import { Box, Button } from '@mui/material';
import GroupMatrixStockTile from './GroupMatrixStockTile';

export default function MatrixStockPreview({ stocks, limit, title, metric, onSelectStock, onSelectStocks }) {
  return <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(72px, 1fr))', gap: '3px' }}>
    {stocks.slice(0, limit).map(stock => <GroupMatrixStockTile key={stock.symbol} stock={stock} metric={metric} onSelect={onSelectStock} />)}
    {stocks.length > limit && <Button size="small" sx={{ gridColumn: '1 / -1', minHeight: 28, fontSize: 11 }}
      aria-label={`+${stocks.length - limit} more in ${title}`}
      onClick={() => onSelectStocks({ title, stocks })}>+{stocks.length - limit} more</Button>}
  </Box>;
}
