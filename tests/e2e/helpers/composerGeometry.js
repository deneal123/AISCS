async function watchComposerGeometry(page) {
  await page.addInitScript(() => {
    window.__composerGeometryTransitions = [];
    document.addEventListener('transitionrun', event => {
      if (event.target.closest?.('[data-composer-container]')
        && /^(width|height|min-|max-|padding|margin|font-size|line-height|letter-spacing|flex)/.test(event.propertyName)) {
        window.__composerGeometryTransitions.push({ property: event.propertyName,
          label: event.target.getAttribute('aria-label'), transition: getComputedStyle(event.target).transitionProperty });
      }
    }, true);
  });
}

async function sampleComposerGeometry(page) {
  return page.evaluate(() => new Promise(resolve => {
    const mismatches = [];
    let frames = 0;
    const sample = () => {
      const container = [...document.querySelectorAll('[data-composer-container]')]
        .find(node => node.getClientRects().length && node.getBoundingClientRect().width > 0);
      const button = container?.querySelector('button[aria-label^="Режим:"]');
      if (button) {
        const style = getComputedStyle(container);
        const width = container.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const compact = innerWidth < 768 || width < 600;
        if (button.innerText.includes('Режим:') === compact) {
          mismatches.push({ width, compact, label: button.innerText });
        }
      }
      if (++frames < 24) requestAnimationFrame(sample);
      else resolve({ mismatches, transitions: window.__composerGeometryTransitions });
    };
    requestAnimationFrame(sample);
  }));
}

async function trackComposerBounds(page) {
  await page.addInitScript(() => {
    const state = { frames: 0, samples: [] };
    window.__composerBoundsDiagnostics = state;
    const sample = () => {
      const container = document.querySelector('[data-composer-container]');
      if (container) {
        const bounds = ['Режим:', 'Личность:', 'Модель:'].map(prefix => {
          const node = container.querySelector(`button[aria-label^="${prefix}"]`);
          if (!node) return null;
          const rect = node.getBoundingClientRect();
          return [rect.x, rect.y, rect.width, rect.height];
        });
        state.frames += 1;
        state.samples.push({ time: performance.now(), visibility: document.visibilityState,
          pixelRatio: devicePixelRatio, screen: [window.screen.width, window.screen.height],
          viewport: [innerWidth, innerHeight, window.visualViewport?.width, window.visualViewport?.height,
            window.visualViewport?.scale, window.visualViewport?.offsetTop], bounds });
        if (state.samples.length > 180) state.samples.shift();
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
}

async function attachComposerBounds(page, info) {
  if (page.isClosed()) return;
  const data = await page.evaluate(() => window.__composerBoundsDiagnostics);
  if (data) await info.attach('composer-bounds-diagnostics', {
    body: Buffer.from(JSON.stringify(data)), contentType: 'application/json',
  });
}

module.exports = { watchComposerGeometry, sampleComposerGeometry, trackComposerBounds, attachComposerBounds };
