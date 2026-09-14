import { memo, useEffect, useState } from 'react';
import { Box } from '@mui/material';
import GroupMatrixGrid from './GroupMatrixGrid';
import GroupMatrixClusters from './GroupMatrixClusters';

const Grid = memo(GroupMatrixGrid);
const Clusters = memo(GroupMatrixClusters);
// Keep a visited layout's last props while inactive: filters only render the
// visible tree. Reusing its bounded DOM avoids rebuilding it on every switch.
const LayoutFrame = memo(function LayoutFrame({ active, View, layout, ...props }) {
  return <Box data-matrix-layout={layout} aria-hidden={!active} inert={active ? undefined : ''}
    sx={{ position: active ? 'relative' : 'absolute', top:0, left:0, width:'100%',
      visibility:active ? 'visible' : 'hidden', pointerEvents:active ? 'auto' : 'none' }}>
    <View {...props} />
  </Box>;
}, (previous, next) => !previous.active && !next.active);

export default function GroupMatrixLayouts({ layout, ...props }) {
  const [visited, setVisited] = useState(() => [layout]);
  useEffect(() => {
    setVisited(previous => previous.includes(layout) ? previous : [...previous, layout]);
  }, [layout]);
  return <Box sx={{position:'relative'}}>
    {[['grid', Grid], ['clusters', Clusters]].map(([name, View]) =>
      (name === layout || visited.includes(name)) && <LayoutFrame key={name}
        active={name === layout} layout={name} View={View} {...props} />)}
  </Box>;
}
