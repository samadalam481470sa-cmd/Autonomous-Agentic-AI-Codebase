import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: /bundle\.spec\.mjs$/,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['github']] : 'line',
  use: {
    baseURL: process.env.BUNDLE_URL || 'http://127.0.0.1:8131',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
