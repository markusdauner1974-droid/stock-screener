import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Box, Paper, Popper, Typography } from '@mui/material';
import { stockMetadataRows } from './groupMatrixStockDetails';

// One delegated inspector for the map avoids a tooltip instance on every tile.
export default function GroupMatrixTileInspector({ stocks, data, children }) {
  const [anchor, setAnchor] = useState(null);
  const popupRef = useRef(null);
  const id = useId();
  const bySymbol = useMemo(() => new Map(stocks.map(stock => [stock.symbol, stock])), [stocks]);
  const stock = anchor?.isConnected ? bySymbol.get(anchor.dataset.matrixStock) : null;
  useEffect(() => setAnchor(null), [stocks]);
  useLayoutEffect(() => {
    if (!anchor || !stock) return undefined;
    anchor.setAttribute('aria-describedby', id);
    return () => anchor.removeAttribute('aria-describedby');
  }, [anchor, stock, id]);
  const inspect = event => {
    const tile = event.target.closest?.('[data-matrix-stock]');
    if (tile) setAnchor(tile);
  };
  const leave = event => {
    const related = event.relatedTarget;
    if (related instanceof Node && (anchor?.contains(related) || popupRef.current?.contains(related))) return;
    if (document.activeElement !== anchor) setAnchor(null);
  };
  return <Box onMouseOver={inspect} onFocusCapture={inspect} onMouseOut={leave}
    onBlurCapture={() => setAnchor(null)} onScrollCapture={event => { if (!popupRef.current?.contains(event.target)) setAnchor(null); }}
    onClickCapture={() => setAnchor(null)}
    onKeyDown={event => { if (event.key === 'Escape') setAnchor(null); }}>
    {children}
    <Popper id={id} open={Boolean(stock)} anchorEl={anchor} placement="top-start" sx={{ zIndex: 1500 }}
      modifiers={[{name:'offset', options:{offset:[0,8]}}]}>
      {stock && <Paper ref={popupRef} onMouseLeave={leave}
        sx={{ p:1.5, width:360, maxWidth:'90vw', maxHeight:'70vh', overflowY:'auto', border:'1px solid', borderColor:'divider' }}>
        <Typography variant="subtitle2">{stock.symbol} · {stock.company_name || stock.symbol}</Typography>
        <Box component="dl" sx={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:0.5, my:1 }}>
          {stockMetadataRows(stock, data).map(([label,value]) => <Box key={label} sx={{display:'contents'}}>
            <Typography component="dt" variant="caption" color="text.secondary">{label}</Typography>
            <Typography component="dd" variant="caption" sx={{m:0, overflowWrap:'anywhere'}}>{value}</Typography>
          </Box>)}
        </Box>
      </Paper>}
    </Popper>
  </Box>;
}
