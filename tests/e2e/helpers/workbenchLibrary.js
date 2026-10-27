const { expect } = require('@playwright/test');

async function triggerWorkbenchLibrary(page) {
    await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
    const action = page.getByRole('button', { name: 'Библиотека', exact: true });
    if (!await action.isVisible()) {
      const menu = page.getByRole('button', { name: 'Меню', exact: true });
      if (await menu.isVisible()) await menu.click();
      else await page.getByRole('button', { name: 'Переключить сайдбар', exact: true }).click();
    }
    await action.click();
}

async function openWorkbenchLibrary(page, { project = false, refresh = false } = {}) {
  const panel = page.getByTestId('workbench-library');
  if (!await panel.isVisible()) {
    await triggerWorkbenchLibrary(page);
    await expect(panel).toBeVisible();
  }
  if (refresh) await panel.getByRole('button', { name: 'Обновить библиотеку', exact: true }).click();
  if (project) {
    const target = panel.getByRole('combobox', { name: 'Куда добавить файл', exact: true });
    await target.focus(); await target.press('ArrowDown');
    await page.getByRole('option', { name: /^PDF:/ }).click();
  }
  return panel;
}

async function closeWorkbenchLibrary(page) {
  await page.getByRole('button', { name: 'Закрыть библиотеку', exact: true }).click();
  await expect(page.getByTestId('workbench-library')).toHaveCount(0);
}

module.exports = { triggerWorkbenchLibrary, openWorkbenchLibrary, closeWorkbenchLibrary };
