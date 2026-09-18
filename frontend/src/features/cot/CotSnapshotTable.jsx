import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  FormControl,
  InputLabel,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Typography,
} from '@mui/material';

import { formatCotNumber, formatCotPercent, priceStateLabel } from './cotPresentation';

const COLUMNS = [
  ['display_name', 'Market'],
  ['long', 'Long'],
  ['short', 'Short'],
  ['net', 'Net'],
  ['net_pct_open_interest', 'Net / OI'],
  ['percentile_3y', '3Y Percentile'],
  ['trend', '12W Net Trend'],
  ['price_change_pct', 'Price Change'],
];

const compare = (left, right, direction) => {
  if (left === null || left === undefined) return right === null || right === undefined ? 0 : 1;
  if (right === null || right === undefined) return -1;
  const result = typeof left === 'string'
    ? left.localeCompare(right)
    : left - right;
  return direction === 'asc' ? result : -result;
};

const Delta = ({ value }) => (
  <Typography component="span" variant="caption" color={value > 0 ? 'success.main' : value < 0 ? 'error.main' : 'text.secondary'} sx={{ ml: 0.5 }}>
    {value === null ? '—' : `${value > 0 ? '+' : ''}${formatCotNumber(value)}`}
  </Typography>
);

const NetTrend = ({ values }) => {
  if (!values?.length) return <span>—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 76},${22 - ((value - min) / span) * 20}`).join(' ');
  return (
    <svg width="78" height="24" viewBox="0 0 78 24" role="img" aria-label={`12-week net trend ending at ${formatCotNumber(values.at(-1))}`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
};

const CotSnapshotTable = ({ snapshot, onSelectInstrument, selectedSlug = null }) => {
  const [category, setCategory] = useState('all');
  const [sort, setSort] = useState(null);
  const categories = useMemo(() => [...new Set((snapshot?.rows || []).map((row) => row.category))], [snapshot]);
  const rows = useMemo(() => {
    const filtered = (snapshot?.rows || []).filter((row) => category === 'all' || row.category === category);
    if (!sort) return filtered;
    const value = (row) => (sort.key === 'trend' ? row.net_trend.at(-1) : row[sort.key]);
    return filtered
      .map((row, index) => ({ row, index }))
      .sort((a, b) => compare(value(a.row), value(b.row), sort.direction) || a.index - b.index)
      .map((item) => item.row);
  }, [category, snapshot, sort]);

  const changeSort = (key) => setSort((current) => (
    current?.key === key
      ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
      : { key, direction: key === 'display_name' ? 'asc' : 'desc' }
  ));
  const select = (slug) => onSelectInstrument?.(slug);

  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
        <Typography variant="h6" component="h3">All curated markets</Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel id="cot-category-label">Category</InputLabel>
            <Select
              native
              labelId="cot-category-label"
              label="Category"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              inputProps={{ 'aria-label': 'COT table category' }}
            >
              <option value="all">All categories</option>
              {categories.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
            </Select>
          </FormControl>
          <Button variant="outlined" onClick={() => setSort(null)}>Restore curated order</Button>
        </Box>
      </Box>
      <TableContainer sx={{ maxHeight: 520 }}>
        <Table stickyHeader size="small" aria-label="COT positioning snapshot">
          <TableHead>
            <TableRow>
              {COLUMNS.map(([key, label]) => (
                <TableCell key={key} sortDirection={sort?.key === key ? sort.direction : false}>
                  <TableSortLabel
                    active={sort?.key === key}
                    direction={sort?.key === key ? sort.direction : 'asc'}
                    onClick={() => changeSort(key)}
                  >
                    {label}
                  </TableSortLabel>
                </TableCell>
              ))}
              <TableCell>Price Context</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.slug}
                hover
                selected={row.slug === selectedSlug}
                tabIndex={0}
                onClick={() => select(row.slug)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    select(row.slug);
                  }
                }}
                sx={{ cursor: 'pointer' }}
              >
                <TableCell><Typography variant="body2">{row.display_name}</Typography><Typography variant="caption" color="text.secondary">{row.focal_label}</Typography></TableCell>
                <TableCell>{formatCotNumber(row.long)}<Delta value={row.delta_long} /></TableCell>
                <TableCell>{formatCotNumber(row.short)}<Delta value={row.delta_short} /></TableCell>
                <TableCell>{formatCotNumber(row.net)}<Delta value={row.delta_net} /></TableCell>
                <TableCell>{formatCotPercent(row.net_pct_open_interest)}</TableCell>
                <TableCell>{row.percentile_status === 'available' ? formatCotPercent(row.percentile_3y, 0) : 'Building'}</TableCell>
                <TableCell><NetTrend values={row.net_trend} /></TableCell>
                <TableCell>{formatCotPercent(row.price_change_pct)}</TableCell>
                <TableCell>{priceStateLabel(row.price_mapping_kind, row.price_coverage_state)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
};

export default CotSnapshotTable;
