import { useMemo } from 'react';
import { Box, Button } from '@mui/material';
import GroupMatrixStockTile from './GroupMatrixStockTile';
import { packMatrixStocks } from './groupMatrixPacking';

export default function MatrixBubblePreview({ stocks, title, metric, onSelectStock, onSelectStocks }) {
  const bubbles = useMemo(() => packMatrixStocks(stocks, metric), [stocks, metric]);
  return <>
    <Box className="group-matrix-bubble-pack" sx={{ position:'relative', width:256, height:256, mx:'auto' }}>
      {bubbles.map(bubble => <GroupMatrixStockTile key={bubble.stock.symbol} stock={bubble.stock}
        bubble={bubble} metric={metric} onSelect={onSelectStock} />)}
    </Box>
    {stocks.length > bubbles.length && <Button size="small" sx={{ width:'100%', minHeight:32, fontSize:11 }}
      aria-label={`+${stocks.length - bubbles.length} more in ${title}`}
      onClick={() => onSelectStocks({ title, stocks })}>+{stocks.length - bubbles.length} more</Button>}
  </>;
}
