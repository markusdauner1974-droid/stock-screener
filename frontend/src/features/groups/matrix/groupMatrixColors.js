import { groupRsTone } from '../groupRsVisualEncoding';

export const MATRIX_METRICS = {
  price_change_1d: { label:'1-Day Change', colorStep:1 },
  price_change_1w: { label:'1-Week Change', colorStep:2 },
  price_change_1m: { label:'1-Month Change', colorStep:4 },
  rs_rating: { label:'Stock RS' },
};

const RS_COLORS = { 'down-strong': '#a83240', 'down-soft': '#854349', neutral: '#444c5c', 'up-soft': '#326a50', 'up-strong': '#23713e' };
const DAILY_COLORS = ['#b52d40', '#91404a', '#6b4854', '#444c5c', '#3e6255', '#327749', '#23783e'];
export function matrixColor(value, metric, theme) {
  if (!Number.isFinite(value)) return {
    backgroundColor: theme.palette.mode === 'dark' ? '#303540' : '#e8eaef',
    color: theme.palette.text.primary, missing: true,
  };
  return { backgroundColor: metric === 'rs_rating' ? RS_COLORS[groupRsTone(value)]
    : DAILY_COLORS[Math.round(Math.max(-3, Math.min(3, value / MATRIX_METRICS[metric].colorStep))) + 3], color: '#fff', missing: false };
}
export function matrixLegend(metric) {
  if (metric === 'rs_rating') return {values:[20,30,50,70,80], labels:['≤20','>20–30','>30–<70','70–<80','≥80']};
  const step = MATRIX_METRICS[metric].colorStep;
  const boundaries = [-2.5,-1.5,-0.5,0.5,1.5,2.5].map(value=>value * step);
  return { values:[-3,-2,-1,0,1,2,3].map(value=>value * step),
    labels:[`<${boundaries[0]}%`, ...boundaries.slice(0,-1).map((value,i)=>`${value}–<${boundaries[i+1]}%`), `≥${boundaries[5]}%`] };
}
export const formatMatrixValue = (value, metric) => !Number.isFinite(value) ? '—'
  : metric === 'rs_rating' ? value.toFixed(1) : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
const capFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2,
});
export const formatCap = value => Number.isFinite(value) ? capFormatter.format(value) : 'Unknown cap';
