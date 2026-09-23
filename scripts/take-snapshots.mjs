/**
 * Boots Vite, visits primary hash routes, and saves full-page PNGs.
 * Usage: node scripts/take-snapshots.mjs [--page home,catalog,product,cart,checkout,account,about,lookbook,docs,admin]
 *
 * Output: artifacts/snapshots/<viewport>-<page>-<theme>.png
 */

import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { QA_CART, QA_CHECKOUT, QA_STORAGE_KEYS, QA_WISHLIST } from './qaFixtures.mjs';

const PORT = 4174;
const BASE_URL = `http://127.0.0.1:${PORT}/`;
const OUT_DIR = path.resolve('artifacts/snapshots');
const REVEAL_MS = 700;

const VIEWPORTS = [
  { id: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false },
  { id: 'tablet', viewport: { width: 768, height: 1024 }, isMobile: false },
  { id: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true },
];

const ROUTES = [
  { id: 'home', hash: '#/' },
  { id: 'catalog', hash: '#/catalog' },
  { id: 'product', hash: '#/product/p1' },
  { id: 'cart', hash: '#/cart' },
  { id: 'checkout', hash: '#/checkout' },
  { id: 'account', hash: '#/account' },
  { id: 'about', hash: '#/about' },
  { id: 'lookbook', hash: '#/lookbook' },
  { id: 'docs', hash: '#/docs' },
  { id: 'admin', hash: '#/admin' },
];

const argIdx = process.argv.indexOf('--page');
const wantOnly = argIdx !== -1 ? new Set(process.argv[argIdx + 1].split(',').map((item) => item.trim())) : null;

async function serverIsReady() {
  try {
    const response = await fetch(BASE_URL);
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForServer() {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 30_000) {
    if (await serverIsReady()) return;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Vite did not become ready at ${BASE_URL}`);
}

async function startServer() {
  if (await serverIsReady()) return null;

  const viteEntry = path.resolve('node_modules', 'vite', 'bin', 'vite.js');
  const server = spawn(process.execPath, [viteEntry, '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
  });

  server.stderr.on('data', (data) => process.stderr.write(data));
  await waitForServer();
  return server;
}

async function triggerReveal(page) {
  await page.evaluate(async () => {
    const step = Math.floor(window.innerHeight * 0.65);
    for (let y = 0; y < document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((resolve) => setTimeout(resolve, 70));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(REVEAL_MS);
}

async function setTheme(page, theme) {
  await page.evaluate((nextTheme) => {
    document.documentElement.setAttribute('data-theme', nextTheme);
  }, theme);
  await page.waitForTimeout(200);
}

async function createPage(browser, viewport) {
  const context = await browser.newContext({
    viewport: viewport.viewport,
    isMobile: viewport.isMobile,
  });

  await context.addInitScript(({ cart, checkout, storageKeys, wishlist }) => {
    window.localStorage.setItem(storageKeys.cart, JSON.stringify(cart));
    window.localStorage.setItem(storageKeys.checkout, JSON.stringify(checkout));
    window.localStorage.setItem(storageKeys.wishlist, JSON.stringify(wishlist));
    document.cookie = 'gm_cookie_consent=essential; path=/; max-age=15552000; SameSite=Lax';
  }, { cart: QA_CART, checkout: QA_CHECKOUT, storageKeys: QA_STORAGE_KEYS, wishlist: QA_WISHLIST });

  const page = await context.newPage();
  page.on('console', () => {});
  return { context, page };
}

await fs.mkdir(OUT_DIR, { recursive: true });

console.log('Starting dev server...');
const server = await startServer();
const browser = await chromium.launch({ headless: true });

try {
  for (const viewport of VIEWPORTS) {
    const { context, page } = await createPage(browser, viewport);

    for (const route of ROUTES) {
      if (wantOnly && !wantOnly.has(route.id)) continue;

      for (const theme of ['light', 'dark']) {
        await page.goto(`${BASE_URL}${route.hash}`, { waitUntil: 'networkidle' });
        await setTheme(page, theme);
        await triggerReveal(page);

        const file = path.join(OUT_DIR, `${viewport.id}-${route.id}-${theme}.png`);
        await page.screenshot({ path: file, fullPage: true });
        console.log(`Saved ${path.relative(process.cwd(), file)}`);
      }
    }

    await context.close();
  }

  console.log(`Snapshots saved to ${OUT_DIR}`);
} finally {
  await browser.close();
  if (server) server.kill();
}
