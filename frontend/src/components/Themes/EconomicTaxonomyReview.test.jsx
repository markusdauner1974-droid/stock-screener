import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import EconomicTaxonomyReview from './EconomicTaxonomyReview';

const review = {
  generation_id: 'generation-1',
  allocations: [{
    legacy_theme_cluster_id: 7,
    allocation_kind: 'claim',
    allocation_key: 'petroleum',
    destination_theme_id: 'theme-oil',
    reviewed_exclusion: false,
  }],
  reconciliation: [{
    economic_theme_id: 'theme-ai',
    memberships: [{
      canonical_symbol: 'MU',
      market: 'US',
      state: 'conflict_review_required',
      admission_state: 'review_only',
    }],
  }],
  operation_previews: [{
    operation_request_id: 'operation-1',
    operation_kind: 'split',
    preview_hash: 'preview-abc',
    reviewer_reason: 'Needs evidence allocation',
    stale: true,
    status: 'rejected',
  }],
};

describe('EconomicTaxonomyReview', () => {
  it('shows split allocations, Social conflicts, and auditable operation previews', () => {
    render(<EconomicTaxonomyReview review={review} onRefresh={vi.fn()} />);

    expect(screen.getByText(/Legacy theme 7/)).toBeInTheDocument();
    expect(screen.getByText(/petroleum.*theme-oil/)).toBeInTheDocument();
    expect(screen.getByText(/MU.*US/)).toBeInTheDocument();
    expect(screen.getByText(/conflict review required.*review only/)).toBeInTheDocument();
    expect(screen.getByText(/preview-abc/)).toBeInTheDocument();
    expect(screen.getByText(/Needs evidence allocation/)).toBeInTheDocument();
    expect(screen.getAllByText(/Stale preview/)).toHaveLength(2);
  });

  it('offers an explicit refresh for stale previews', () => {
    const onRefresh = vi.fn();
    render(<EconomicTaxonomyReview review={review} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole('button', { name: /refresh review/i }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});
