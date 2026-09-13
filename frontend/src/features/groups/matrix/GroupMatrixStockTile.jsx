import { useTheme } from '@mui/material/styles';
import { formatMatrixValue, matrixColor } from './groupMatrixColors';
import { sectorLabel, groupLabel } from './groupMatrixModel';
import './groupMatrixTiles.css';

export default function GroupMatrixStockTile({ stock, metric, onSelect }) {
  const theme = useTheme();
  const { missing, ...colors } = matrixColor(stock[metric], metric, theme);
  const value = formatMatrixValue(stock[metric], metric);
  const description = `${stock.symbol} ${value}, ${sectorLabel(stock.sector)}, ${groupLabel(stock.ibd_industry_group)}, ${stock.cap_tier}`;
  return <button type="button" className="group-matrix-stock" data-matrix-stock={stock.symbol} aria-label={description}
    onClick={() => onSelect(stock)} style={{ ...colors, '--matrix-focus': theme.palette.primary.main,
      backgroundImage: missing ? 'repeating-linear-gradient(135deg, transparent 0 4px, #88888818 4px 6px)' : 'none' }}>
    <span className="group-matrix-stock-symbol">{stock.symbol}</span>
    <span className="group-matrix-stock-value">{value}</span>
  </button>;
}
