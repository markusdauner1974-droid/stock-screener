import { useEffect, useRef } from 'react';
import { Box, Button, Typography, useMediaQuery } from '@mui/material';
import { useVirtualizer } from '@tanstack/react-virtual';
import { groupLabel, sectorLabel } from './groupMatrixModel';
import MatrixStockPreview from './MatrixStockPreview';

function ClusterColumn({ cards, tier, metric, onSelectStock, onSelectStocks }) {
  const scrollRef = useRef(null);
  const small = useMediaQuery('(max-width:599px)');
  const virtual = useVirtualizer({ count: cards.length, getScrollElement: () => scrollRef.current,
    estimateSize: i => cards[i].kind === 'sector' ? 38 : 54 + Math.ceil(Math.min(24, cards[i].stocks.length) / 3) * (small ? 47 : 35) + (cards[i].stocks.length > 24 ? 32 : 0),
    getItemKey: i => cards[i].key, overscan: 1, initialRect: { width: 250, height: 600 } });
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = 0; }, [cards]);
  return <Box sx={{ minWidth: 270, flex: '1 0 270px', borderRight: '1px solid', borderColor: 'divider' }}>
    <Typography sx={{ height: 38, px: 1, py: 1, fontSize: 12, fontWeight: 700 }}>{tier.label}</Typography>
    <Box ref={scrollRef} role="region" aria-label={`${tier.label} industry clusters`} tabIndex={0} sx={{ height: 600, overflowY: 'auto' }}>
      <Box sx={{ height: virtual.getTotalSize(), position: 'relative' }}>
        {virtual.getVirtualItems().map(item => {
          const card = cards[item.index];
          return <Box key={item.key} sx={{ position: 'absolute', top: 0, left: 0, width: '100%', height: item.size, p: 0.5, transform: `translateY(${item.start}px)` }}>
            {card.kind === 'sector' ? <Typography sx={{ bgcolor: 'action.hover', p: 0.75, fontSize: 12, fontWeight: 800 }}>{sectorLabel(card.sector)}</Typography>
              : <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, p: 0.5 }}>
                <Button size="small" title={groupLabel(card.group)} sx={{ height: 36, maxWidth: '100%', display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', textTransform: 'none', fontSize: 11, textAlign: 'left' }}
                  onClick={() => onSelectStocks({ title: `${groupLabel(card.group)} · ${tier.label}`, stocks: card.stocks })}>{groupLabel(card.group)} ({card.stocks.length})</Button>
                <MatrixStockPreview stocks={card.stocks} limit={24} title={`${groupLabel(card.group)} · ${tier.label}`}
                  metric={metric} onSelectStock={onSelectStock} onSelectStocks={onSelectStocks} />
              </Box>}
          </Box>;
        })}
      </Box>
    </Box>
  </Box>;
}
export default function GroupMatrixClusters({ model, tiers, ...props }) {
  return <Box role="region" aria-label="Stock matrix clusters" sx={{ display: 'flex', overflowX: 'auto', border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
    {tiers.map(tier => <ClusterColumn key={tier.id} cards={model.clustersByTier[tier.id] || []} tier={tier} {...props} />)}
  </Box>;
}
