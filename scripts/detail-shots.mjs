/**
 * Detail viewport crops (desktop) for visual review — reads from an already-running
 * Vite server on 4174. Saves to artifacts/detail/<page>-<theme>.png (viewport-only).
 * Usage: node scripts/detail-shots.mjs
 */
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import { QA_CART, QA_CHECKOUT, QA_STORAGE_KEYS, QA_WISHLIST } from './qaFixtures.mjs';

const BASE_URL = 'http://127.0.0.1:4174/';
const OUT_DIR = path.resolve('artifacts/detail');

const SHOTS = [
  { id: 'catalog', hash: '#/catalog', scrollY: 320 },
  { id: 'product', hash: '#/product/p1', scrollY: 120 },
  { id: 'checkout', hash: '#/checkout', scrollY: 80 },
  { id: 'home-cards', hash: '#/', scrollY: 1450 },
];

await fs.mkdir(OUT_DIR, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(({ cart, checkout, storageKeys, wishlist }) => {
    window.localStorage.setItem(storageKeys.cart, JSON.stringify(cart));
    window.localStorage.setItem(storageKeys.checkout, JSON.stringify(checkout));
    window.localStorage.setItem(storageKeys.wishlist, JSON.stringify(wishlist));
    document.cookie = 'gm_cookie_consent=essential; path=/; max-age=15552000; SameSite=Lax';
  }, { cart: QA_CART, checkout: QA_CHECKOUT, storageKeys: QA_STORAGE_KEYS, wishlist: QA_WISHLIST });
  const page = await context.newPage();

  for (const shot of SHOTS) {
    for (const theme of ['light', 'dark']) {
      await page.goto(`${BASE_URL}${shot.hash}`, { waitUntil: 'networkidle' });
      await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
      await page.evaluate((y) => window.scrollTo(0, y), shot.scrollY);
      await page.waitForTimeout(700);
      const file = path.join(OUT_DIR, `${shot.id}-${theme}.png`);
      await page.screenshot({ path: file, fullPage: false });
      console.log(`Saved ${path.relative(process.cwd(), file)}`);
    }
  }
} finally {
  await browser.close();
}
