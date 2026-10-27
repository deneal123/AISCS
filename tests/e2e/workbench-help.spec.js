const { test, expect } = require('@playwright/test');
const { installLibraryApi } = require('./helpers/libraryApi');

test.use({ serviceWorkers: 'block' });

for (const width of [1440, 393]) {
  test(`IDE agent help reopens immediately and preserves keyboard ownership at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await installLibraryApi(page);
    const requests = [];
    const id = '20000000-0000-0000-0000-000000000001';
    const repository = { repository_id: id, name: 'Справка IDE', state: 'registered' };
    const runtime = { repository_id: id, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } };
    const git = { repository_id: id, generation: 'a'.repeat(64), initialized: true, branch: 'main' };
    await page.route('**/api/chats/**/ide/**', route => {
      const path = new URL(route.request().url()).pathname;
      requests.push(path);
      const json = path.endsWith('/repositories') ? { items: [repository], next_offset: null }
        : path.endsWith('/prepare') ? { repository, runtime, git }
          : path.endsWith('/runtime') ? runtime : path.endsWith('/git') ? git
            : path.endsWith('/clone-attempt') ? { attempt: null }
              : { repository_id: id, generation: 'a'.repeat(64), entries: [], truncated: false };
      return route.fulfill({ json });
    });
    await page.getByRole('button', { name: 'IDE', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Состояние среды: Среда доступна', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Обновить IDE', exact: true })).toBeEnabled();
    if (width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
    const trigger = page.getByRole('button', { name: 'Об агенте IDE', exact: true });
    const before = requests.length;
    await trigger.focus();
    await trigger.press('Enter');
    // Escape must work before the next animation frame transfers focus.
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.press('Enter');
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Справка IDE');
    const close = dialog.getByRole('button', { name: 'Закрыть сведения об агенте', exact: true });
    await expect(close).toBeFocused();
    const box = await dialog.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(box.height).toBeLessThanOrEqual(360);
    await page.screenshot({ path: info.outputPath('agent-help.png'), animations: 'disabled' });
    await close.click();
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(requests.length).toBe(before);
  });
}
