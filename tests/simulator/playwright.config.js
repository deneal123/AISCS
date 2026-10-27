const { defineConfig } = require('@playwright/test');
const path = require('path');

module.exports = defineConfig({
  testDir: __dirname,
  testMatch: '*.live.spec.js',
  workers: 1,
  timeout: 60000,
  retries: 0,
  outputDir: path.resolve(__dirname, '../../../.work/generator-implementation/ui-tests'),
  reporter: [['list'], ['json', { outputFile: path.resolve(__dirname, '../../../.work/generator-implementation/ui-tests.json') }]],
  use: {
    baseURL: process.env.SIMULATION_E2E_URL || 'http://localhost:8095',
    storageState: process.env.SIMULATION_E2E_STATE,
    channel: process.env.SIMULATION_E2E_CHANNEL || 'msedge',
    headless: true,
    contextOptions: { reducedMotion: 'reduce' },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'laptop', use: { viewport: { width: 1366, height: 768 } } },
    { name: 'desktop', use: { viewport: { width: 1920, height: 1080 } } },
  ],
});
