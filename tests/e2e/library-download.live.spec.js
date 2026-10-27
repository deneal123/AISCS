const { test, expect } = require('@playwright/test');
const { openWorkbenchLibrary } = require('./helpers/workbenchLibrary');
const { createHash } = require('crypto');

const enabled = process.env.E2E_LIVE_LIBRARY_DOWNLOAD === '1';
const token = process.env.E2E_AUTH_TOKEN || '';
const fixture = JSON.parse(process.env.E2E_LIBRARY_DOWNLOAD_FIXTURE || '[]');
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';
const surface = process.env.E2E_LIBRARY_DOWNLOAD_SURFACE || 'chat';

// Download response URLs contain signed capabilities. Do not retain browser
// traces, HAR, screenshots, video or downloaded user bytes for this live check.
test.use({ trace: 'off', video: 'off', screenshot: 'off' });
test.setTimeout(90_000);

async function verifyDownload(page, link, item, keyboard) {
  const pending = page.waitForEvent('download', { timeout: 30_000 });
  if (keyboard) {
    await link.focus();
    await expect(link).toBeFocused();
    await link.press('Enter');
  } else {
    await link.click();
  }
  let download;
  try {
    download = await pending;
    expect(await download.failure(), 'owned_download_failed').toBeNull();
    expect(download.suggestedFilename(), 'owned_download_name_mismatch').toBe(item.original_name);
    const source = await download.createReadStream();
    expect(source, 'owned_download_stream_missing').not.toBeNull();
    const digest = createHash('sha256');
    let size = 0;
    for await (const chunk of source) {
      size += chunk.length;
      expect(size, 'owned_download_size_exceeded').toBeLessThanOrEqual(item.artifact_size);
      digest.update(chunk);
    }
    expect(size, 'owned_download_size_mismatch').toBe(item.artifact_size);
    expect(digest.digest('hex'), 'owned_download_digest_mismatch').toBe(item.artifact_sha256);
  } finally {
    if (download) await download.delete();
  }
}

test('delivered document cards download owned files before and after reload', async ({ context, page }, testInfo) => {
  test.skip(!enabled || !token || fixture.length !== 2, 'Requires read-only delivered PDF/ZIP fixture.');
  test.skip(!['chromium', 'mobile-chrome'].includes(testInfo.project.name), 'Desktop/mobile Chromium acceptance.');
  const viewport = testInfo.project.name === 'chromium'
    ? { width: 1440, height: 900 } : { width: 393, height: 851 };
  await page.setViewportSize(viewport);
  await context.addCookies([{ name: 'auth_token', value: token, url: baseURL }]);
  await context.addInitScript((value) => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', value);
  }, token);

  for (const item of fixture) {
    await page.goto(`/chat/${item.thread_id}?surface=${surface}`, { waitUntil: 'domcontentloaded' });
    await openWorkbenchLibrary(page);
    const link = page.locator(`a[href$="/api/service/files/v1/${item.id}/download"]`).first();
    await expect(link, 'owned_download_action_missing').toBeVisible({ timeout: 25_000 });
    await verifyDownload(page, link, item, true);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await openWorkbenchLibrary(page);
    await expect(link, 'owned_download_action_missing_after_reload').toBeVisible({ timeout: 25_000 });
    await verifyDownload(page, link, item, false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth
      <= document.documentElement.clientWidth), 'chat_horizontal_overflow').toBeTruthy();
  }
});
