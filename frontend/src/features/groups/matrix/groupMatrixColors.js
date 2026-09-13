import { groupRsTone } from '../groupRsVisualEncoding';

const RS_COLORS = { 'down-strong': '#a83240', 'down-soft': '#854349', neutral: '#444c5c', 'up-soft': '#326a50', 'up-strong': '#23713e' };
const DAILY_COLORS = ['#b52d40', '#91404a', '#6b4854', '#444c5c', '#3e6255', '#327749', '#23783e'];
export function matrixColor(value, metric, theme) {
  if (!Number.isFinite(value)) return {
    backgroundColor: theme.palette.mode === 'dark' ? '#303540' : '#e8eaef',
    color: theme.palette.text.primary, missing: true,
  };
  return { backgroundColor: metric === 'rs_rating' ? RS_COLORS[groupRsTone(value)]
    : DAILY_COLORS[Math.round(Math.max(-3, Math.min(3, value))) + 3], color: '#fff', missing: false };
}
export const formatMatrixValue = (value, metric) => !Number.isFinite(value) ? '—'
  : metric === 'rs_rating' ? value.toFixed(1) : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
const capFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2,
});
export const formatCap = value => Number.isFinite(value) ? capFormatter.format(value) : 'Unknown cap';
