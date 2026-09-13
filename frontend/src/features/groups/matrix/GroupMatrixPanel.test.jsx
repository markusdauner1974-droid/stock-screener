import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import GroupMatrixPanel from './GroupMatrixPanel';
import { DEFAULT_MATRIX_PREFERENCES } from './groupMatrixModel';

const stocks = Array.from({length: 30}, (_, i) => ({ symbol: `STK${String(i).padStart(2,'0')}`,
  company_name: `Company ${i}`, sector: 'Technology', ibd_industry_group: 'Software',
  cap_tier: 'mid', market_cap_usd: 3e9, price_change_1d: i === 0 ? null : 0, rs_rating: 85 }));
const data = { available: true, market: 'US', as_of_date: '2026-09-11', metadata_read_at: '2026-09-13',
  tiers: [{ id: 'mid', label: 'Mid' }], stocks, coverage: { stock_count:30, universe_count:30, ibd_mapped_count:30 } };
function Harness() {
  const [preferences, onPreferencesChange] = useState(DEFAULT_MATRIX_PREFERENCES);
  return <GroupMatrixPanel data={data} preferences={preferences} onPreferencesChange={onPreferencesChange} />;
}
describe('Matrix panel', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(640);
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1200);
  });
  afterEach(() => vi.restoreAllMocks());
  it('retains search and metric when changing layouts', () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole('textbox', {name: /Search/}), {target: {value:'STK01'}});
    fireEvent.click(screen.getByRole('button', {name:'Clusters'}));
    expect(screen.getByRole('textbox', {name:/Search/})).toHaveValue('STK01');
    expect(screen.getByRole('button', {name:/STK01.*0.00%/})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name:/STK02.*0.00%/})).not.toBeInTheDocument();
  });
  it('opens every overflow constituent and stock metadata', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', {name:/\+18 more/}));
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByText('30 stocks')).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole('button', {name:/STK00/}));
    expect(within(drawer).getByText('Company 0')).toBeInTheDocument();
    expect(within(drawer).getByText('Stock RS')).toBeInTheDocument();
  });
  it('distinguishes unavailable data from no matching filters', () => {
    render(<GroupMatrixPanel data={{available:false, reason:'missing_ibd_mappings'}} preferences={DEFAULT_MATRIX_PREFERENCES} />);
    expect(screen.getByText(/IBD classifications are not available/)).toBeInTheDocument();
  });
});
