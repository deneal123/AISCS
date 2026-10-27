// Test configuration policy without importing the CLI's dynamic modules into
// Jest's VM. Native renderer capability is verified by the separate live suite.
jest.mock('@playwright/test', () => ({
  defineConfig: (value) => value,
  devices: {
    'Desktop Chrome': { viewport: { width: 1280, height: 720 } },
    'Pixel 5': { viewport: { width: 393, height: 727 } },
  },
}));

describe('live Work browser qualification', () => {
  const original = process.env.E2E_LIVE_WORK_HUB;
  const originalBaseUrl = process.env.E2E_BASE_URL;

  afterEach(() => {
    if (original === undefined) delete process.env.E2E_LIVE_WORK_HUB;
    else process.env.E2E_LIVE_WORK_HUB = original;
    if (originalBaseUrl === undefined) delete process.env.E2E_BASE_URL;
    else process.env.E2E_BASE_URL = originalBaseUrl;
    jest.resetModules();
  });

  it.each([false, true])('uses full Chromium only for opt-in live runs: %s', (live) => {
    if (live) process.env.E2E_LIVE_WORK_HUB = '1';
    else delete process.env.E2E_LIVE_WORK_HUB;
    jest.resetModules();
    const config = require('../e2e/playwright.config');
    const project = (name) => config.projects.find((item) => item.name === name);
    expect(project('chromium').use.channel).toBe(live ? 'chromium' : undefined);
    expect(project('mobile-chrome').use.channel).toBe(live ? 'chromium' : undefined);
    expect(project('chromium').use.viewport).toEqual(
      live ? { width: 1440, height: 900 } : { width: 1280, height: 720 },
    );
    expect(project('mobile-chrome').use.viewport).toEqual(
      live ? { width: 393, height: 851 } : { width: 393, height: 727 },
    );
    for (const name of ['firefox', 'webkit', 'mobile-safari', 'tablet']) {
      expect(project(name).use.channel).toBeUndefined();
    }
  });

  it.each([false, true])('keeps interception ownership separate from external live SW: %s', (external) => {
    if (external) process.env.E2E_BASE_URL = 'http://localhost:3001';
    else delete process.env.E2E_BASE_URL;
    jest.resetModules();
    const config = require('../e2e/playwright.config');
    expect(config.use.serviceWorkers).toBe(external ? 'allow' : 'block');
  });
});
