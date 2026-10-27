const { expect } = require('@playwright/test');

async function checkComposerInvitation(page) {
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const surface = page.locator('[data-composer-input-surface]');
  await expect(input).toBeVisible();
  await expect(input).toBeEnabled();
  await input.focus();
  expect(await surface.evaluate(element => getComputedStyle(element, '::before').content)).toBe('none');
  const focusedBounds = await surface.boundingBox();
  await input.blur();
  await expect(surface).toHaveAttribute('data-action-hint', 'idle');
  await expect.poll(() => surface.evaluate(element => getComputedStyle(element, '::before').animationName)).toBe('gold-edge-run');
  expect(await surface.boundingBox()).toEqual(focusedBounds);
  // Не оставляем активную анимацию в замерах геометрии соседнего сценария.
  await input.focus();
  expect(await surface.evaluate(element => getComputedStyle(element, '::before').content)).toBe('none');
}

module.exports = { checkComposerInvitation };
