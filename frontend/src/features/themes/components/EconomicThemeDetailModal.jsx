import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  Paper,
  Stack,
  Typography,
} from '@mui/material';

const METRICS = [
  ['technical_attention', 'Technical Attention'],
  ['fundamental_attention', 'Fundamental Attention'],
  ['narrative_attention', 'Narrative Attention'],
  ['emerging', 'Emerging'],
  ['broad_confirmation', 'Broad Confirmation'],
];

const displayMetric = (metric = {}) => {
  if (metric.availability !== 'available') {
    return `Unavailable${metric.components?.reason ? ` — ${metric.components.reason}` : ''}`;
  }
  if (metric.percentile !== null && metric.percentile !== undefined) {
    return `${Number(metric.percentile).toFixed(0)} percentile`;
  }
  if (metric.raw_value !== null && metric.raw_value !== undefined) {
    return String(metric.raw_value);
  }
  return 'Available';
};

function Section({ title, children }) {
  return (
    <Box component="section" sx={{ mt: 2 }}>
      <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
      <Box sx={{ mt: 0.75 }}>{children}</Box>
    </Box>
  );
}

function EmptyAwareList({ rows, renderRow }) {
  if (!rows?.length) {
    return <Typography color="text.secondary">No published records.</Typography>;
  }
  return <Stack spacing={0.5}>{rows.map(renderRow)}</Stack>;
}

export default function EconomicThemeDetailModal({
  open,
  theme,
  generationId,
  onClose,
}) {
  if (!theme) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>{theme.display_name}</DialogTitle>
      <DialogContent dividers>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 2 }}>
          <Chip label={theme.lifecycle || 'lifecycle unavailable'} />
          <Chip label={`Identity ${theme.economic_theme_id}`} variant="outlined" />
          {generationId && <Chip label={`Generation ${generationId}`} variant="outlined" />}
        </Stack>

        <Typography>{theme.definition || 'Definition unavailable.'}</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          {theme.mechanism || 'Economic mechanism unavailable.'}
        </Typography>

        <Grid container spacing={1.5} sx={{ mt: 1 }}>
          {METRICS.map(([key, label]) => (
            <Grid item xs={12} sm={6} md={4} key={key}>
              <Paper variant="outlined" sx={{ p: 1.5 }} data-testid={`metric-${key}`}>
                <Typography variant="caption" color="text.secondary">{label}</Typography>
                <Typography fontWeight={700}>{displayMetric(theme.metrics?.[key])}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>

        <Section title="Evidence provenance">
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <Typography>Direct evidence: {theme.direct_observation_count ?? 0}</Typography>
            <Typography>Derived evidence: {theme.derived_observation_count ?? 0}</Typography>
            <Typography>
              Independent source families: {theme.deduplicated_source_family_count ?? 0}
            </Typography>
          </Stack>
        </Section>

        <Divider sx={{ my: 2 }} />
        <Section title="Facets">
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            {(theme.facets || []).map((facet) => (
              <Chip
                key={`${facet.dimension}:${facet.value || facet.display_value}`}
                label={`${facet.dimension}: ${facet.display_value || facet.value}`}
                size="small"
              />
            ))}
            {!theme.facets?.length && <Typography color="text.secondary">No facets.</Typography>}
          </Stack>
        </Section>

        <Section title="Relationships">
          <EmptyAwareList
            rows={theme.relationships}
            renderRow={(row, index) => (
              <Typography key={row.id || index}>
                {row.kind} · {row.source_theme_id || theme.economic_theme_id} → {row.target_theme_id}
              </Typography>
            )}
          />
        </Section>

        <Section title="Structured signals">
          <EmptyAwareList
            rows={theme.signals}
            renderRow={(row, index) => (
              <Typography key={row.signal_id || index}>
                {row.signal_kind} · {row.canonical_symbol || 'theme-wide'}
              </Typography>
            )}
          />
        </Section>

        <Section title="Developments">
          <EmptyAwareList
            rows={theme.developments}
            renderRow={(row, index) => (
              <Typography key={row.observation_id || index}>
                {row.classification || 'unclassified'} · {row.analysis_channel || 'channel unavailable'}
              </Typography>
            )}
          />
        </Section>

        <Section title="Constituents">
          <EmptyAwareList
            rows={theme.constituents}
            renderRow={(row, index) => (
              <Typography key={row.exposure_id || index}>
                {row.canonical_symbol || `Security ${row.security_id}`} · {row.market || 'market unavailable'} · {row.exposure_kind}
              </Typography>
            )}
          />
        </Section>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
