import apiClient from './client';
import {
  normalizeCotCatalog,
  normalizeCotHistory,
  normalizeCotSnapshot,
} from '../features/cot/cotContract';

export const getCotCatalog = async () => normalizeCotCatalog(
  (await apiClient.get('/v1/cot/instruments')).data,
);

export const getCotHistory = async (slug, range = '1y') => {
  const normalizedSlug = String(slug || '').trim().toLowerCase();
  const response = await apiClient.get(
    `/v1/cot/instruments/${encodeURIComponent(normalizedSlug)}/history`,
    { params: { range } },
  );
  return normalizeCotHistory(response.data, {
    expectedSlug: normalizedSlug,
    expectedRange: range,
  });
};

export const getCotSnapshot = async () => normalizeCotSnapshot(
  (await apiClient.get('/v1/cot/snapshot')).data,
);
