// Замер начинается при настоящем нажатии, а не после стабилизации панели.
async function watchFirstPickerFrame(trigger) {
  await trigger.evaluate(element => {
    const frames = [];
    window.__pickerOpeningFrames = frames;
    element.addEventListener('pointerdown', () => {
      const sample = () => {
        const dialog = [...document.querySelectorAll('[role="dialog"]')]
          .find(node => getComputedStyle(node).visibility !== 'hidden');
        if (dialog) {
          const { x, y, width, height } = dialog.getBoundingClientRect();
          frames.push({ x, y, width, height });
        }
        if (frames.length < 6) requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    }, { once: true, capture: true });
  });
}

async function firstPickerFrames(page) {
  await page.waitForFunction(() => window.__pickerOpeningFrames?.length === 6);
  return page.evaluate(() => window.__pickerOpeningFrames);
}

module.exports = { watchFirstPickerFrame, firstPickerFrames };
