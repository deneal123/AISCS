const { defineConfig, devices } = require("@playwright/test");
const path = require('path');

const externalBaseUrl = process.env.E2E_BASE_URL;
const standalonePort = Number(process.env.E2E_PORT || 3000);
if (!Number.isInteger(standalonePort) || standalonePort < 1 || standalonePort > 65535) {
  throw new Error(`E2E_PORT must be a valid TCP port, got: ${process.env.E2E_PORT}`);
}
const baseURL = externalBaseUrl || `http://localhost:${standalonePort}`;
const webServer = externalBaseUrl
  ? undefined
  : {
    command: `node scripts/serve-e2e.js build ${standalonePort}`,
    cwd: path.resolve(__dirname, '../..'),
    port: standalonePort,
    reuseExistingServer: false,
    timeout: 30 * 1000,
  };

module.exports = defineConfig({
  testDir: __dirname,
  timeout: 30 * 1000,
  retries: 0,
  use: {
    headless: true,
    baseURL,
    // Save full trace and screenshots for each run to aid debugging in CI/artifacts
    trace: 'on',
    screenshot: 'on',
    video: 'retain-on-failure',
    // Увеличиваем таймауты для более реалистичных тестов
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },
  // Store Playwright report and attachments in repo-level tmp_e2e for CI artifact collection
  outputDir: '../../tmp_e2e/playwright-report',
  // With E2E_BASE_URL, test the explicitly supplied dev stack. Otherwise run
  // the built frontend through the standalone SPA-aware server; never accept
  // an unrelated process that happens to own port 3000.
  webServer,
  projects: [
    // Desktop браузеры
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
    // Мобильные устройства
    {
      name: "mobile-chrome",
      use: { ...devices["Pixel 5"] },
    },
    {
      name: "mobile-safari",
      use: { ...devices["iPhone 12"] },
    },
    // Планшеты
    {
      name: "tablet",
      use: { ...devices["iPad (gen 7)"] },
    },
    // Тест на мобильном с ландшафтной ориентацией
    {
      name: "mobile-landscape",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 851, height: 393 },
      },
    },
  ],
});
