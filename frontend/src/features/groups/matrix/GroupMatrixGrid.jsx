import { useEffect, useRef } from 'react';
import { Box, Button, Typography, useMediaQuery } from '@mui/material';
import { useVirtualizer } from '@tanstack/react-virtual';
import { groupLabel, sectorLabel } from './groupMatrixModel';
import MatrixStockPreview from './MatrixStockPreview';

export default function GroupMatrixGrid({ model, tiers, metric, onSelectStock, onSelectStocks }) {
  const scrollRef = useRef(null);
  const small = useMediaQuery('(max-width:599px)');
  const rows = model.gridRows;
  const virtual = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current,
    estimateSize: index => rows[index].kind === 'sector' ? 38 : small ? 238 : 190,
    getItemKey: index => rows[index].key, overscan: 2, initialRect: { width: 1400, height: 640 }, scrollMargin: 38 });
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = 0; }, [model]);
  const labelWidth = small ? 140 : 220;
  const columns = `${labelWidth}px repeat(${tiers.length}, minmax(238px, 1fr))`;
  return <Box ref={scrollRef} role="region" aria-label="Stock matrix grid, industries by market cap" tabIndex={0}
    sx={{ height: 640, overflow: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
    <Box sx={{ minWidth: labelWidth + tiers.length * 238 }}>
      <Box sx={{ position: 'sticky', top: 0, zIndex: 4, display: 'grid', gridTemplateColumns: columns, bgcolor: 'background.paper', height: 38, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ position: 'sticky', left: 0, bgcolor: 'background.paper', px: 1, py: 1, fontSize: 12, fontWeight: 700 }}>{small ? 'Sector / IBD' : 'Sector / IBD industry'}</Box>
        {tiers.map(tier => <Box key={tier.id} sx={{ px: 1, py: 1, fontSize: 12, fontWeight: 700 }}>{tier.label}</Box>)}
      </Box>
      <Box sx={{ height: virtual.getTotalSize(), position: 'relative' }}>
        {virtual.getVirtualItems().map(item => {
          const row = rows[item.index];
          return <Box key={item.key} sx={{ position: 'absolute', top: 0, left: 0, width: '100%', height: item.size,
            transform: `translateY(${item.start - 38}px)`, display: 'grid', gridTemplateColumns: columns, borderBottom: '1px solid', borderColor: 'divider' }}>
            {row.kind === 'sector' ? <Box sx={{ gridColumn: '1 / -1', bgcolor: 'action.hover', px: 1, py: 1 }}>
              <Typography sx={{ position: 'sticky', left: 8, width: 'fit-content', fontSize: 12, fontWeight: 800 }}>{sectorLabel(row.sector)}</Typography>
            </Box> : <>
              <Box sx={{ position: 'sticky', left: 0, zIndex: 2, bgcolor: 'background.paper', p: 1, borderRight: '1px solid', borderColor: 'divider' }}>
                <Button size="small" sx={{ justifyContent: 'flex-start', textAlign: 'left', textTransform: 'none' }}
                  onClick={() => onSelectStocks({ title: `${sectorLabel(row.sector)} / ${groupLabel(row.group)}`, stocks: row.stocks })}>{groupLabel(row.group)}</Button>
                <Typography variant="caption" display="block" color="text.secondary">{row.stocks.length} stocks</Typography>
              </Box>
              {tiers.map(tier => <Box key={tier.id} sx={{ p: 0.75, borderRight: '1px solid', borderColor: 'divider' }}>
                <MatrixStockPreview stocks={row.stocksByTier[tier.id] || []} limit={12}
                  title={`${groupLabel(row.group)} · ${tier.label}`} metric={metric} onSelectStock={onSelectStock} onSelectStocks={onSelectStocks} />
              </Box>)}
            </>}
          </Box>;
        })}
      </Box>
    </Box>
  </Box>;
}
