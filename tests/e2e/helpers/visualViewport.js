// Управляемая геометрия клавиатуры, не приёмка нативной клавиатуры iOS.
async function installVisualViewport(page) {
  const initialViewport = page.viewportSize();
  await page.addInitScript((initial) => {
    const viewport = new EventTarget();
    // До разбора meta viewport мобильный браузер ещё использует широкую область
    // страницы. Не закрепляем её ошибочную высоту в подмене visualViewport.
    Object.assign(viewport, { height: initial?.height ?? innerHeight, width: initial?.width ?? innerWidth,
      offsetTop: 0, offsetLeft: 0, scale: 1 });
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    window.setTestVisualViewport = (height, offsetTop = 0) => {
      Object.assign(viewport, { height, offsetTop });
      viewport.dispatchEvent(new Event('resize'));
      viewport.dispatchEvent(new Event('scroll'));
    };
  }, initialViewport);
}
module.exports = { installVisualViewport };
