import { useQuery } from '@tanstack/react-query';

import { fetchStaticJson } from './dataClient';
import {
  cotCatalogQueryKey,
  cotHistoryQueryKey,
  normalizeStaticCotIndex,
  normalizeCotHistory,
  requireSafeCotPath,
  sliceCotHistory,
} from '../features/cot/cotContract';

export const getStaticCotIndex = async (rootManifest) => {
  const path = rootManifest?.assets?.cot?.path;
  if (!path) throw new Error('COT data is not advertised by the root manifest');
  requireSafeCotPath(path, 'root COT index path');
  if (!path.endsWith('/index.json')) throw new Error('Invalid root COT index path');
  return normalizeStaticCotIndex(await fetchStaticJson(path));
};

export const getStaticCotHistory = async (rawIndex, slug, range = '1y') => {
  const index = normalizeStaticCotIndex(rawIndex);
  const entry = index.histories[slug];
  if (!entry) throw new Error(`COT instrument ${slug} is not advertised`);
  const history = normalizeCotHistory(await fetchStaticJson(entry.path), {
    expectedSlug: slug,
    expectedRange: '5y',
    expectedPublicationId: index.publication_id,
  });
  return sliceCotHistory(history, range);
};

export const useStaticCotIndex = (rootManifest) => {
  const path = rootManifest?.assets?.cot?.path || null;
  return useQuery({
    queryKey: cotCatalogQueryKey('static', null, path),
    queryFn: () => getStaticCotIndex(rootManifest),
    enabled: Boolean(path),
    staleTime: Infinity,
    gcTime: Infinity,
  });
};

export const useStaticCotHistory = (index, slug, range = '1y') => {
  const entry = index?.histories?.[slug];
  return useQuery({
    queryKey: cotHistoryQueryKey({
      mode: 'static',
      publicationId: index?.publication_id ?? null,
      slug,
      range,
      path: entry?.path ?? null,
    }),
    queryFn: () => getStaticCotHistory(index, slug, range),
    enabled: Boolean(entry),
    staleTime: Infinity,
    gcTime: Infinity,
  });
};
