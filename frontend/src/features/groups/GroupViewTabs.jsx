import { Box, Tab, Tabs, ToggleButton, ToggleButtonGroup } from '@mui/material';
import { RRG_SCOPE_LABELS } from '../../utils/rrgScopes';

export default function GroupViewTabs({ view, onView, scope, onScope, rrgAvailable, availableScopes = [], matrixAvailable = true, sx }) {
  return <Box sx={sx}>
    <Tabs value={view} onChange={(_, v) => onView(v)} aria-label="Group views" sx={{ mb: 1 }}>
      {['table', ...(rrgAvailable ? ['rrg'] : []), ...(matrixAvailable ? ['matrix'] : [])].map(value =>
        <Tab key={value} id={`group-tab-${value}`} aria-controls={`group-panel-${value}`} value={value} label={value === 'rrg' ? 'RRG' : value === 'matrix' ? 'Matrix' : 'Table'} />)}
    </Tabs>
    {view === 'rrg' && availableScopes.length > 1 && <ToggleButtonGroup exclusive size="small" value={scope} onChange={(_, v) => v && onScope(v)}>
      {availableScopes.map(v => <ToggleButton key={v} value={v}>{RRG_SCOPE_LABELS[v]}</ToggleButton>)}
    </ToggleButtonGroup>}
  </Box>;
}
