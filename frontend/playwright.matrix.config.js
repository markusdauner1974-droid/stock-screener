import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/smoke', testMatch: 'group-matrix.spec.js', timeout: 120000,
  expect: { timeout: 45000 }, workers: 1,
  use: { headless:true, actionTimeout:45000, channel:'chrome', trace:'retain-on-failure' },
  projects: [
    { name:'live', use:{baseURL:'http://127.0.0.1:4175'} },
    { name:'static', use:{baseURL:'http://127.0.0.1:4176'} },
  ],
  webServer: [
    { command:'npm run build -- --outDir node_modules/.cache/matrix-live && npm run preview -- --outDir node_modules/.cache/matrix-live --host 127.0.0.1 --port 4175', port:4175, reuseExistingServer:false, timeout:120000, env:{VITE_STATIC_SITE:'false'} },
    { command:'npm run build -- --outDir node_modules/.cache/matrix-static && npm run preview -- --outDir node_modules/.cache/matrix-static --host 127.0.0.1 --port 4176', port:4176, reuseExistingServer:false, timeout:120000, env:{VITE_STATIC_SITE:'true'} },
  ],
});
