import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import CotSnapshotTable from './CotSnapshotTable';
import { cotSnapshotFixture } from './__fixtures__/cotResponses';

const snapshotWithGold = () => ({
  ...cotSnapshotFixture,
  rows: [
    ...cotSnapshotFixture.rows,
    {
      ...cotSnapshotFixture.rows[0],
      slug: 'gold',
      display_name: 'Gold',
      category: 'metals',
      instrument_order: 19,
      focal_participant: 'managed_money',
      focal_label: 'Managed Money',
      net: -20,
      delta_net: -5,
      price_mapping_kind: 'etf_proxy',
      price_coverage_state: 'partial',
      net_trend: [-10, -20],
    },
  ],
});

describe('CotSnapshotTable', () => {
  it('renders all metrics in curated order and selects rows by click or keyboard', () => {
    const onSelectInstrument = vi.fn();
    render(<CotSnapshotTable snapshot={snapshotWithGold()} onSelectInstrument={onSelectInstrument} />);

    ['Market', 'Long', 'Short', 'Net', 'Net / OI', '3Y Percentile', '12W Net Trend', 'Price Change', 'Price Context']
      .forEach((heading) => expect(screen.getByRole('columnheader', { name: new RegExp(`^${heading.replace('/', '\\/')}$`, 'i') })).toBeInTheDocument());
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText('S&P 500')).toBeInTheDocument();
    expect(within(rows.at(-1)).getByText('Gold')).toBeInTheDocument();
    expect(screen.getByText('Managed Money')).toBeInTheDocument();
    expect(screen.getByText(/ETF proxy · Partial/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Gold'));
    expect(onSelectInstrument).toHaveBeenCalledWith('gold');
    fireEvent.keyDown(screen.getByRole('row', { name: /Nasdaq-100/i }), { key: 'Enter' });
    expect(onSelectInstrument).toHaveBeenCalledWith('nasdaq-100');
  });

  it('filters by category, sorts numerics, and restores curated order', () => {
    render(<CotSnapshotTable snapshot={snapshotWithGold()} onSelectInstrument={() => {}} />);

    fireEvent.change(screen.getByLabelText('COT table category'), { target: { value: 'metals' } });
    expect(screen.getByText('Gold')).toBeInTheDocument();
    expect(screen.queryByText('S&P 500')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('COT table category'), { target: { value: 'all' } });
    fireEvent.click(screen.getByRole('button', { name: /^Net$/i }));
    fireEvent.click(screen.getByRole('button', { name: /Restore curated order/i }));
    expect(screen.getAllByRole('row').slice(1)[0]).toHaveTextContent('S&P 500');
  });
});
