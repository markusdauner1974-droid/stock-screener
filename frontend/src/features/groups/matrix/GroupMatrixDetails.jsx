import { useRef } from 'react';
import { Box, Button, Drawer, Typography, ListItemButton, Divider } from '@mui/material';
import { useVirtualizer } from '@tanstack/react-virtual';
import { formatCap, formatMatrixValue } from './groupMatrixColors';
import { groupLabel, sectorLabel } from './groupMatrixModel';

function ConstituentList({ stocks, onSelectStock }) {
  const ref = useRef(null);
  const virtual = useVirtualizer({ count: stocks.length, getScrollElement: () => ref.current,
    estimateSize: () => 56, overscan: 3, initialRect: { width: 420, height: 560 } });
  return <Box ref={ref} sx={{ height: '65vh', overflow: 'auto' }} role="list" aria-label="Matching stocks">
    <Box sx={{ height: virtual.getTotalSize(), position: 'relative' }}>
      {virtual.getVirtualItems().map(item => {
        const stock = stocks[item.index];
        return <ListItemButton key={stock.symbol} role="button" aria-label={`Open ${stock.symbol} details`}
          onClick={() => onSelectStock(stock)} sx={{ position: 'absolute', top: item.start, height: 56, width: '100%', display: 'flex', justifyContent: 'space-between' }}>
          <Box><Typography fontWeight={700}>{stock.symbol}</Typography><Typography variant="caption">{stock.company_name}</Typography></Box>
          <Typography variant="caption">{formatMatrixValue(stock.price_change_1d, 'price_change_1d')}</Typography>
        </ListItemButton>;
      })}
    </Box>
  </Box>;
}
export default function GroupMatrixDetails({ selection, onClose, onSelectStock, onSelectStocks, matchingStocks, data }) {
  const stock = selection?.stock;
  const details = stock && [
    ['Market', data.market], ['Sector', sectorLabel(stock.sector)], ['IBD industry', groupLabel(stock.ibd_industry_group)],
    ['Classification source', stock.classification_source || 'Unclassified'],
    ['Classification confidence', Number.isFinite(stock.classification_confidence) ? `${(stock.classification_confidence * 100).toFixed(0)}%` : '—'],
    ['Market cap (USD)', formatCap(stock.market_cap_usd)],
    ['1-Day Change', formatMatrixValue(stock.price_change_1d, 'price_change_1d')],
    ['Stock RS', formatMatrixValue(stock.rs_rating, 'rs_rating')],
    ['Daily data', data.as_of_date || '—'], ['Metadata read', data.metadata_read_at || '—'],
    ['Fundamentals updated', stock.fundamentals_updated_at || 'Not recorded'],
    ['Classification updated', stock.classification_updated_at || 'Not recorded'],
  ];
  return <Drawer anchor="right" open={Boolean(selection)} onClose={onClose} ModalProps={{ disableRestoreFocus: true }}
    PaperProps={{ role: 'dialog', 'aria-modal': true, 'aria-label': stock ? `${stock.symbol} details` : selection?.title,
      sx: { width: { xs: '100%', sm: 460 }, maxWidth: '100vw', p: 2 } }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography variant="h6">{stock ? stock.symbol : selection?.title}</Typography>
      <Button onClick={onClose} autoFocus>Close</Button>
    </Box>
    {stock ? <>
      <Typography color="text.secondary" sx={{ mb: 2 }}>{stock.company_name}</Typography>
      <Box component="dl" sx={{ m: 0 }}>{details.map(([label, value]) => <Box key={label} sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Typography component="dt" variant="body2" color="text.secondary">{label}</Typography>
        <Typography component="dd" variant="body2" sx={{ m: 0, overflowWrap: 'anywhere' }}>{value}</Typography>
      </Box>)}</Box>
      <Typography variant="caption" color="text.secondary" sx={{ my: 2 }}>Cap and classification use latest stored metadata. Automated classifications are estimates.</Typography>
      <Button onClick={() => onSelectStocks({ title: `${groupLabel(stock.ibd_industry_group)} · current filters`,
        stocks: matchingStocks.filter(s => s.sector === stock.sector && s.ibd_industry_group === stock.ibd_industry_group) })}>View industry constituents</Button>
    </> : <>
      <Typography variant="body2" sx={{ my: 1 }}>{selection?.stocks?.length || 0} stocks</Typography>
      <Divider />
      {selection && <ConstituentList stocks={selection.stocks} onSelectStock={onSelectStock} />}
    </>}
  </Drawer>;
}
