const fs = require('fs');
const puppeteer = require('puppeteer-core');
const axe = require('axe-core');

const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  '/usr/bin/chromium-browser',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);

const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));

async function run() {
  if (!executablePath) {
    throw new Error('No Chromium-compatible browser found. Set PUPPETEER_EXECUTABLE_PATH.');
  }
  const browser = await puppeteer.launch({
    executablePath,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--headless=new'],
  });

  const page = await browser.newPage();
  await page.goto(process.env.AXE_BASE_URL || 'http://localhost:3000', { waitUntil: 'networkidle2', timeout: 60000 });
  // Auth bootstrap can briefly render a loading shell. Scan the actual page,
  // not that transient shell, otherwise heading and landmark rules are false
  // positives on a healthy landing route.
  await page.waitForSelector('h1', { visible: true, timeout: 15000 });

  // Inject axe source and run
  await page.evaluate(axe.source);
  const results = await page.evaluate(async () => await axe.run());

  fs.writeFileSync('axe-report.json', JSON.stringify(results, null, 2));
  console.log('axe report written to axe-report.json');

  await browser.close();

  if (results.violations.length) {
    console.error(`${results.violations.length} axe violation(s) found`);
    process.exitCode = 1;
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
