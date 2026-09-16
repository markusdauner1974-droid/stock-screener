import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import CotPositioningTab from './CotPositioningTab';
import { getCotCatalog, getCotHistory, getCotSnapshot } from '../../api/cot';
import {
  cotCatalogFixture,
  cotHistoryFixture,
  cotSnapshotFixture,
} from './__fixtures__/cotResponses';

vi.mock('../../api/cot', () => ({
  getCotCatalog: vi.fn(),
  getCotHistory: vi.fn(),
  getCotSnapshot: vi.fn(),
}));

const renderTab = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><CotPositioningTab /></QueryClientProvider>);
};

describe('CotPositioningTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getCotCatalog.mockResolvedValue(cotCatalogFixture);
    getCotHistory.mockImplementation(async (slug, range) => ({
      ...cotHistoryFixture,
      slug,
      display_name: slug === 'sp-500' ? 'S&P 500' : 'Nasdaq-100',
      range,
    }));
    getCotSnapshot.mockResolvedValue(cotSnapshotFixture);
  });

  it('loads defaults and refetches for instrument and range controls', async () => {
    renderTab();
    expect(await screen.findByRole('heading', { name: /COT Positioning/i })).toBeInTheDocument();
    await waitFor(() => expect(getCotHistory).toHaveBeenCalledWith('sp-500', '1y'));
    expect(getCotSnapshot).toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('COT instrument'), { target: { value: 'nasdaq-100' } });
    await waitFor(() => expect(getCotHistory).toHaveBeenCalledWith('nasdaq-100', '1y'));
    await screen.findByLabelText('COT instrument');
    fireEvent.click(screen.getByRole('button', { name: '3Y' }));
    await waitFor(() => expect(getCotHistory).toHaveBeenCalledWith('nasdaq-100', '3y'));
  });

  it('keeps the snapshot table visible when history fails', async () => {
    getCotHistory.mockRejectedValue(new Error('history unavailable'));
    renderTab();
    expect(await screen.findByText('S&P 500')).toBeInTheDocument();
    expect(await screen.findByText(/Unable to load COT positioning/i)).toBeInTheDocument();
  });
});
