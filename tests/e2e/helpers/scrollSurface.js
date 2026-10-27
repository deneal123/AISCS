// Mobile WebKit has no mouse.wheel API. Exercise the existing accessible
// scroll owner with a native key instead of injecting a synthetic scrollTop.
async function scrollSurface(page, region, { browserName, isMobile }, delta = 1200) {
  const keyboard = browserName === 'webkit' && isMobile;
  if (keyboard) {
    await region.focus();
    await page.keyboard.press('PageDown');
  } else {
    await region.hover();
    await page.mouse.wheel(0, delta);
  }
  return keyboard;
}

module.exports = { scrollSurface };
