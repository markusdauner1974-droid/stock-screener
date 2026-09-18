import { Box, Paper, Typography } from '@mui/material';

import { formatCotNumber, formatCotPercent } from './cotPresentation';

const SummaryValue = ({ label, value, secondary = null }) => (
  <Paper variant="outlined" sx={{ p: 1.25, minWidth: 0 }}>
    <Typography variant="caption" color="text.secondary" display="block">{label}</Typography>
    <Typography variant="subtitle2" sx={{ fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
    {secondary && <Typography variant="caption" color="text.secondary">{secondary}</Typography>}
  </Paper>
);

const CotSummaryStrip = ({ summary }) => {
  if (!summary) return null;
  const percentile = summary.percentileStatus === 'available'
    ? formatCotPercent(summary.percentile3y, 0)
    : 'Insufficient 3Y history';
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(6, 1fr)' }, gap: 1 }}>
      <SummaryValue label="Report Date" value={summary.reportDate} />
      <SummaryValue label={`${summary.focalLabel} Long`} value={formatCotNumber(summary.long)} />
      <SummaryValue label={`${summary.focalLabel} Short`} value={formatCotNumber(summary.short)} />
      <SummaryValue label={`${summary.focalLabel} Net`} value={formatCotNumber(summary.net)} />
      <SummaryValue label="3Y Percentile" value={percentile} />
      <SummaryValue label="Tuesday-to-Tuesday Price Change" value={formatCotPercent(summary.priceChangePct)} />
    </Box>
  );
};

export default CotSummaryStrip;
