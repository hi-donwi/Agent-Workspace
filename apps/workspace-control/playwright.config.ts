import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './test', fullyParallel: false, workers: 1,
  timeout: 30_000, expect: { timeout: 8_000 },
  use: { baseURL: 'http://127.0.0.1:18765', screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: {
    command: 'python3 test/server.py', url: 'http://127.0.0.1:18765',
    reuseExistingServer: false, timeout: 30_000,
  },
});
