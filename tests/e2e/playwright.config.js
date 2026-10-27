const { defineConfig, devices } = require("@playwright/test");
const path = require('path');

const externalBaseUrl = process.env.E2E_BASE_URL;
const standalonePort = Number(process.env.E2E_PORT || 3000);
if (!Number.isInteger(standalonePort) || standalonePort < 1 || standalonePort > 65535) {
  throw new Error(`E2E_PORT must be a valid TCP port, got: ${process.env.E2E_PORT}`);
}
const baseURL = externalBaseUrl || `http://localhost:${standalonePort}`;
// The default headless shell has no PDF viewer. Real Document Forge acceptance
// needs full Chromium; keep mocked suites and other browser engines unchanged.
const liveWorkEnabled = process.env.E2E_LIVE_WORK_HUB === '1';
const liveChromiumChannel = liveWorkEnabled ? 'chromium' : undefined;
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
    // Compiled mocked suites must own all network interception. A service
    // worker can bypass page.route (notably WebKit's lazy admin requests).
    // External authenticated runs retain the real application's SW behavior.
    serviceWorkers: externalBaseUrl ? 'allow' : 'block',
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
      use: {
        ...devices["Desktop Chrome"],
        channel: liveChromiumChannel,
        ...(liveWorkEnabled ? { viewport: { width: 1440, height: 900 } } : {}),
      },
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
      use: {
        ...devices["Pixel 5"],
        channel: liveChromiumChannel,
        // Pixel 5's screen is 393x851, but its default content viewport is
        // 393x727. Acceptance must measure the requested CSS viewport.
        ...(liveWorkEnabled ? { viewport: { width: 393, height: 851 } } : {}),
      },
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
