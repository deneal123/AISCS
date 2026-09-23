/**
 * Визуальные снепшоты GPTHub для ревью дизайна.
 * Бьёт по УЖЕ запущенному dev-серверу (docker frontend на :3010) — ничего не поднимает.
 * Тёмная тема (другой в проекте нет). Публичные страницы снимаются без авторизации,
 * приватные — после логина тест-пользователем (или регистрации, если логин не прошёл).
 *
 * Usage:
 *   node scripts/gpthub-shots.mjs                  # все страницы, desktop+mobile
 *   node scripts/gpthub-shots.mjs --only login,contacts
 *   BASE_URL=http://localhost:3010 EMAIL=.. PASSWORD=.. node scripts/gpthub-shots.mjs
 *
 * Output: artifacts/design/<viewport>-<page>.png (full page)
 */
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const BASE_URL = (process.env.BASE_URL || 'http://localhost:3010').replace(/\/$/, '');
const EMAIL = process.env.EMAIL || 'admin-e2e@example.com';
const PASSWORD = process.env.PASSWORD || 'password1234';
const OUT_DIR = path.resolve('artifacts/design');

const VIEWPORTS = [
  { id: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false },
  { id: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true },
];

// auth:false — публичные; auth:true — нужен залогиненный контекст.
const PAGES = [
  { id: 'login', path: '/login', auth: false },
  { id: 'signup', path: '/signup', auth: false },
  { id: 'contacts', path: '/contacts', auth: false },
  { id: 'legal-offer', path: '/legal/offer', auth: false },
  { id: 'legal-privacy', path: '/legal/privacy', auth: false },
  { id: 'chat', path: '/', auth: true },
  { id: 'billing', path: '/billing', auth: true },
  { id: 'admin', path: '/admin', auth: true },
];

const argIdx = process.argv.indexOf('--only');
const only = argIdx !== -1 ? new Set(process.argv[argIdx + 1].split(',').map((s) => s.trim())) : null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function settle(page) {
  // ждём, пока стихнут анимации входа/reveal и шрифты
  try { await page.evaluate(() => document.fonts && document.fonts.ready); } catch {}
  await sleep(700);
}

async function tryAuth(page) {
  // 1) логин
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle' });
  await settle(page);
  try {
    await page.fill('input[placeholder="you@example.com"]', EMAIL, { timeout: 5000 });
    await page.fill('input[placeholder="Введите пароль"]', PASSWORD, { timeout: 5000 });
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 8000 });
    console.log('  auth: вошли существующим пользователем');
    return true;
  } catch {
    console.log('  auth: логин не прошёл, пробую регистрацию…');
  }
  // 2) регистрация нового пользователя
  const email = `design_${Date.now()}@example.com`;
  await page.goto(`${BASE_URL}/signup`, { waitUntil: 'networkidle' });
  await settle(page);
  try {
    await page.fill('input[placeholder="you@example.com"]', email, { timeout: 5000 });
    await page.fill('input[placeholder="Минимум 8 символов, буквы и цифры"]', 'password1234', { timeout: 5000 });
    await page.fill('input[placeholder="Повторите пароль"]', 'password1234', { timeout: 5000 });
    await page.fill('input[placeholder="Ваше имя"]', 'Designer', { timeout: 5000 });
    await page.click('button[type="submit"]');
    await page.waitForURL((u) => !u.pathname.startsWith('/signup') && !u.pathname.startsWith('/register'), { timeout: 10000 });
    console.log(`  auth: зарегистрировали ${email}`);
    return true;
  } catch (e) {
    console.log('  auth: регистрация тоже не удалась —', e.message.split('\n')[0]);
    return false;
  }
}

await fs.mkdir(OUT_DIR, { recursive: true });
const browser = await chromium.launch({ headless: true });
const wanted = PAGES.filter((p) => !only || only.has(p.id));

try {
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({ viewport: vp.viewport, isMobile: vp.isMobile, deviceScaleFactor: 1 });
    const page = await context.newPage();
    page.on('console', () => {});

    let authed = false;
    if (wanted.some((p) => p.auth)) authed = await tryAuth(page);

    for (const p of wanted) {
      if (p.auth && !authed) { console.log(`  skip ${vp.id}-${p.id} (no auth)`); continue; }
      await page.goto(`${BASE_URL}${p.path}`, { waitUntil: 'networkidle' });
      await settle(page);
      const file = path.join(OUT_DIR, `${vp.id}-${p.id}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log(`Saved ${path.relative(process.cwd(), file)}`);
    }

    await context.close();
  }
  console.log(`\nГотово → ${OUT_DIR}`);
} finally {
  await browser.close();
}
