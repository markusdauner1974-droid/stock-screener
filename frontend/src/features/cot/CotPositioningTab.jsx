import { useEffect, useState } from 'react';
import { Alert, Box } from '@mui/material';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { getCotCatalog, getCotHistory, getCotSnapshot } from '../../api/cot';
import {
  cotCatalogQueryKey,
  cotHistoryQueryKey,
  cotSnapshotQueryKey,
} from './cotContract';
import CotPositioningView from './CotPositioningView';
import CotSnapshotTable from './CotSnapshotTable';

const CotPositioningTab = () => {
  const queryClient = useQueryClient();
  const [selectedSlug, setSelectedSlug] = useState('sp-500');
  const [range, setRange] = useState('1y');
  const catalogQuery = useQuery({
    queryKey: cotCatalogQueryKey('live'),
    queryFn: getCotCatalog,
    staleTime: 60_000,
  });
  const publicationId = catalogQuery.data?.publication?.publication_id || null;
  const historyQuery = useQuery({
    queryKey: cotHistoryQueryKey({
      mode: 'live', publicationId, slug: selectedSlug, range,
    }),
    queryFn: () => getCotHistory(selectedSlug, range, publicationId),
    enabled: publicationId !== null,
    staleTime: 60_000,
  });
  const snapshotQuery = useQuery({
    queryKey: cotSnapshotQueryKey(publicationId),
    queryFn: () => getCotSnapshot(publicationId),
    enabled: publicationId !== null,
    staleTime: 60_000,
  });
  const publicationMismatch = [historyQuery.error, snapshotQuery.error].some(
    (error) => error instanceof Error && /publication identity mismatch/i.test(error.message),
  );

  useEffect(() => {
    if (publicationMismatch) {
      queryClient.invalidateQueries({
        queryKey: cotCatalogQueryKey('live'),
        exact: true,
      });
    }
  }, [publicationMismatch, queryClient]);

  return (
    <Box sx={{ height: '100%', overflow: 'auto', pr: 0.5 }}>
      <Box sx={{ display: 'grid', gap: 1.5 }}>
        <CotPositioningView
          catalog={catalogQuery.data || null}
          history={historyQuery.data || null}
          selectedSlug={selectedSlug}
          range={range}
          onSelectInstrument={setSelectedSlug}
          onRangeChange={setRange}
          isLoading={catalogQuery.isLoading || historyQuery.isLoading}
          error={catalogQuery.error || historyQuery.error}
        />
        {snapshotQuery.data && (
          <CotSnapshotTable
            snapshot={snapshotQuery.data}
            selectedSlug={selectedSlug}
            onSelectInstrument={setSelectedSlug}
          />
        )}
        {snapshotQuery.error && (
          <Alert severity="error">Unable to load the COT market table.</Alert>
        )}
      </Box>
    </Box>
  );
};

export default CotPositioningTab;
