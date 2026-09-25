import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  Typography,
} from '@mui/material';

const words = (value) => String(value || '').replaceAll('_', ' ');

function ReviewSection({ title, empty, children }) {
  return (
    <Box component="section" sx={{ mt: 2 }}>
      <Typography variant="h6">{title}</Typography>
      <Stack spacing={1} sx={{ mt: 1 }}>
        {empty ? <Typography color="text.secondary">None.</Typography> : children}
      </Stack>
    </Box>
  );
}

export default function EconomicTaxonomyReview({ review, onRefresh, isRefreshing = false }) {
  if (!review) {
    return <Alert severity="info">No Economic Taxonomy review snapshot is available.</Alert>;
  }
  const stale = (review.operation_previews || []).some((row) => row.stale);

  return (
    <Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" gap={1}>
        <Box>
          <Typography variant="h5">Economic Taxonomy Review</Typography>
          <Typography color="text.secondary">Generation {review.generation_id}</Typography>
        </Box>
        {stale && (
          <Button variant="outlined" onClick={onRefresh} disabled={isRefreshing}>
            {isRefreshing ? 'Refreshing…' : 'Refresh review'}
          </Button>
        )}
      </Stack>

      {stale && <Alert severity="warning" sx={{ mt: 2 }}>Stale preview — refresh before approval.</Alert>}

      <ReviewSection title="Split allocations" empty={!review.allocations?.length}>
        {(review.allocations || []).map((row, index) => (
          <Card variant="outlined" key={`${row.legacy_theme_cluster_id}:${row.allocation_key}:${index}`}>
            <CardContent>
              <Typography fontWeight={700}>Legacy theme {row.legacy_theme_cluster_id}</Typography>
              <Typography>
                {row.allocation_key} → {row.destination_theme_id || 'reviewed exclusion'}
              </Typography>
              <Chip size="small" label={words(row.allocation_kind)} sx={{ mt: 1 }} />
            </CardContent>
          </Card>
        ))}
      </ReviewSection>

      <Divider sx={{ my: 2 }} />
      <ReviewSection title="Social decision reconciliation" empty={!review.reconciliation?.length}>
        {(review.reconciliation || []).flatMap((group) =>
          (group.memberships || []).map((row, index) => (
            <Card variant="outlined" key={`${group.economic_theme_id}:${row.association_id || index}`}>
              <CardContent>
                <Typography fontWeight={700}>
                  {row.canonical_symbol || `Security ${row.security_id}`} · {row.market || 'market unavailable'}
                </Typography>
                <Typography>{words(row.state)} · {words(row.admission_state)}</Typography>
                {row.state === 'conflict_review_required' && (
                  <Alert severity="error" sx={{ mt: 1 }}>Conflict review required</Alert>
                )}
              </CardContent>
            </Card>
          )),
        )}
      </ReviewSection>

      <Divider sx={{ my: 2 }} />
      <ReviewSection title="Operation previews" empty={!review.operation_previews?.length}>
        {(review.operation_previews || []).map((row) => (
          <Card variant="outlined" key={row.operation_request_id}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography fontWeight={700}>{words(row.operation_kind)}</Typography>
                <Chip size="small" label={words(row.status)} />
                {row.stale && <Chip size="small" color="warning" label="Stale preview" />}
              </Stack>
              <Typography sx={{ mt: 1 }}>Preview hash: {row.preview_hash}</Typography>
              <Typography>Reviewer reason: {row.reviewer_reason || 'Not provided'}</Typography>
            </CardContent>
          </Card>
        ))}
      </ReviewSection>
    </Box>
  );
}
