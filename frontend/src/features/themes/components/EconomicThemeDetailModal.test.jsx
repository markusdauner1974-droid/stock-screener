import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import EconomicThemeDetailModal from './EconomicThemeDetailModal';

const theme = {
  economic_theme_id: 'theme-1',
  display_name: 'AI Memory',
  definition: 'Memory demand caused by AI infrastructure investment.',
  mechanism: 'Accelerator deployments increase high-bandwidth memory demand.',
  lifecycle: 'active',
  aliases: ['HBM'],
  facets: [{ dimension: 'technology', display_value: 'AI' }],
  metrics: {
    technical_attention: { availability: 'available', percentile: 91 },
    fundamental_attention: { availability: 'unavailable', components: { reason: 'insufficient evidence' } },
    narrative_attention: { availability: 'available', raw_value: 12 },
    emerging: { availability: 'available', percentile: 74 },
    broad_confirmation: { availability: 'available', percentile: 88 },
  },
  direct_observation_count: 4,
  derived_observation_count: 2,
  deduplicated_source_family_count: 3,
  relationships: [{ kind: 'specialization', target_theme_id: 'theme-2' }],
  signals: [{ signal_kind: 'breakout', canonical_symbol: 'MU' }],
  developments: [{ classification: 'capacity expansion', analysis_channel: 'narrative' }],
  constituents: [{ canonical_symbol: 'MU', market: 'US', exposure_kind: 'direct' }],
};

describe('EconomicThemeDetailModal', () => {
  it('shows global identity, five ranking views, provenance, and structured evidence', () => {
    render(
      <EconomicThemeDetailModal
        open
        theme={theme}
        generationId="generation-1"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('dialog')).toHaveTextContent('AI Memory');
    expect(screen.getByText(/Identity theme-1/)).toBeInTheDocument();
    for (const label of [
      'Technical Attention',
      'Fundamental Attention',
      'Narrative Attention',
      'Emerging',
      'Broad Confirmation',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.queryByText('Fundamental Momentum')).not.toBeInTheDocument();
    expect(screen.getByTestId('metric-fundamental_attention')).toHaveTextContent(
      'Unavailable',
    );
    expect(screen.getByText(/Direct evidence: 4/)).toBeInTheDocument();
    expect(screen.getByText(/Derived evidence: 2/)).toBeInTheDocument();
    expect(screen.getByText(/Independent source families: 3/)).toBeInTheDocument();
    expect(screen.getByText(/technology: AI/)).toBeInTheDocument();
    expect(screen.getByText(/specialization/)).toBeInTheDocument();
    expect(screen.getByText(/breakout.*MU/i)).toBeInTheDocument();
    expect(screen.getByText(/capacity expansion/i)).toBeInTheDocument();
    expect(screen.getByText(/MU.*US.*direct/i)).toBeInTheDocument();
  });

  it('closes through the dialog action', () => {
    const onClose = vi.fn();
    render(<EconomicThemeDetailModal open theme={theme} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
