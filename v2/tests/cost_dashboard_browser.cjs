// Credential-free browser check using deterministic billing fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const fixtures = {};
  for (const env of ['production', 'development', 'development-legacy']) fixtures[env] = JSON.parse(await fs.readFile(path.join(__dirname, `fixtures/costs-${env}.json`), 'utf8'));
  const routing = {};
  vm.runInNewContext(await fs.readFile(path.join(root, 'agent/public-report-routes.js'), 'utf8'), routing);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    await page.clock.install({ time: new Date('2026-09-18T12:00:00Z') });
    let environment = 'production', payload = fixtures.production, fail = false, legacyHtml = false;
    const errors = [], external = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'https://cost.test') { external.push(url.origin); return route.abort(); }
      if (url.pathname === '/costs.json') return route.fulfill({ status: fail ? 503 : 200, contentType: 'application/json', body: fail ? '' : JSON.stringify(payload) });
      const requested = routing.handler({ request: { uri: url.pathname } }).uri;
      const file = requested === '/' ? 'dev_chat.html' : requested.replace(/^\//, '');
      let body = await fs.readFile(path.join(root, 'agent', file));
      if (file.endsWith('.html')) body = Buffer.from(body.toString().replaceAll('${environment}', environment));
      if (file === 'costs.html' && legacyHtml) body = Buffer.from(body.toString().replace(' id="coverage-label"', ''));
      const contentType = file.endsWith('.css') ? 'text/css' : file.endsWith('.mjs') ? 'text/javascript' : file.endsWith('.png') ? 'image/png' : 'text/html';
      return route.fulfill({ body, contentType });
    });
    const go = async () => { await page.goto('https://cost.test/cost-dashboard'); await page.waitForFunction(() => document.querySelector('#total').textContent !== '–'); };
    await go();
    await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.56');
    assert.equal(await page.locator('#aws').innerText(), '$4.76');
    assert.equal(await page.locator('#openai').innerText(), '$6.80');
    assert.deepEqual(await page.locator('.nav-links a').allTextContents(), ['Chat', 'Cost', 'Evaluation results']);
    assert.equal(await page.locator('.nav-links a[aria-current]').getAttribute('href'), '/cost-dashboard');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.56');
    await page.goto('https://cost.test/cost-dashboard/');
    await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.56');
    await page.keyboard.press('Tab'); assert.equal(await page.locator(':focus').innerText(), 'Skip to costs');
    await page.locator('#daily-details summary').focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#daily-details[open]').count(), 1);
    const checkChart = async () => {
      assert.equal(await page.locator('#daily-rows tr').count(), 30);
      const bars = await page.locator('#trend rect').evaluateAll(nodes => nodes.map(node => ({ date: node.dataset.date, provider: node.dataset.provider, usd: node.dataset.usd, height: Number(node.getAttribute('height')) })));
      for (const bar of bars) {
        assert.equal(bar.usd, payload.daily.find(row => row.date === bar.date)[bar.provider]); assert.ok(bar.height >= 0);
        const index = bar.provider === 'aws' ? 0 : 1;
        assert.equal(await page.locator('#daily-rows tr').filter({ hasText: bar.date }).locator('td').nth(index).getAttribute('data-usd'), bar.usd);
      }
    };
    await checkChart();
    fail = true;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(() => document.querySelector('#state-notice').textContent.includes('Browser refresh failed'));
    assert.equal(await page.locator('#total').innerText(), '$11.56');
    fail = false;
    payload = structuredClone(fixtures.production); payload.environment = 'development';
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#total').innerText(), '$11.56');
    await page.reload(); await page.waitForFunction(() => document.querySelector('#total').textContent === 'Unavailable');
    payload = fixtures.production;
    await go(); await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.56');
    await page.clock.setFixedTime(new Date('2026-09-21T12:00:00Z'));
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(() => document.querySelector('#state-notice').textContent.includes('over 48 hours'));
    await page.clock.setFixedTime(new Date('2026-09-18T12:00:00Z'));
    const output = path.resolve(root, '../test-results/cost-dashboard'); await fs.mkdir(output, { recursive: true });
    await go(); await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.56');
    await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    for (const width of [320, 390, 820, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
    environment = 'development'; payload = fixtures.development;
    await go(); await page.waitForFunction(() => document.querySelector('#aws').textContent === '$5.10');
    assert.equal(await page.locator('#total').innerText(), '$11.90');
    assert.equal(await page.locator('#openai').innerText(), '$6.80');
    assert.match(await page.locator('#deployment').innerText(), /DEVELOPMENT/);
    assert.match(await page.locator('#coverage-label').innerText(), /organization-wide OpenAI/);
    assert.match(await page.locator('#total-note').innerText(), /Development AWS/);
    assert.match(await page.locator('#openai-note').innerText(), /Organization-wide/);
    await checkChart();
    await page.setViewportSize({ width: 320, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    // Unversioned HTML and JS may update separately during preparation.
    legacyHtml = true;
    await go(); await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.90');
    assert.match(await page.locator('.context-line > span').innerText(), /organization-wide OpenAI/);
    await checkChart();
    legacyHtml = false;
    // Signed adjustments and sub-cent costs are never hidden as zero.
    payload = structuredClone(fixtures.development);
    const src = payload.sources.aws_development;
    src.daily.forEach(row => { row.usd = '-0.000000001'; });
    src.aws_services = [{ label: 'AWS Lambda', usd: '-0.000000017' }];
    src.aws_environments = [{ label: 'unallocated', usd: '-0.000000017' }];
    payload.aws_services = src.aws_services; payload.aws_environments = src.aws_environments;
    payload.month_to_date.aws = '-0.000000017'; payload.month_to_date.total = '6.799999983';
    payload.daily.forEach(row => { row.aws = '-0.000000001'; row.total = '0.399999999'; });
    await go(); await page.waitForFunction(() => document.querySelector('#aws').textContent.includes('<$0.01'));
    assert.match(await page.locator('#aws').innerText(), /^−/); await checkChart();
    assert.equal(await page.locator('#allocation').isVisible(), false);
    // Legacy AWS-only data remains readable during the deployment transition.
    payload = fixtures['development-legacy'];
    await go(); await page.waitForFunction(() => document.querySelector('#aws').textContent === '$5.10');
    assert.equal(await page.locator('#total').innerText(), 'Unavailable');
    assert.match(await page.locator('#state-notice').innerText(), /Awaiting the first OpenAI/);
    // A failed first OpenAI refresh migrates the legacy scope and retains AWS.
    payload = structuredClone(payload); payload.scope = 'aws-development+openai-organization';
    payload.sources.openai.status = 'unavailable';
    payload.attempt.status = 'failed'; payload.attempt.sources.openai = 'unavailable';
    await go(); await page.waitForFunction(() => document.querySelector('#aws').textContent === '$5.10');
    assert.equal(await page.locator('#total').innerText(), 'Unavailable');
    assert.match(await page.locator('#state-notice').innerText(), /Daily refresh failed/);
    assert.doesNotMatch(await page.locator('#state-notice').innerText(), /by design|Awaiting/);
    await checkChart();
    // A failed publisher attempt retains the prior amounts and says so.
    environment = 'production'; payload = structuredClone(fixtures.production);
    payload.attempt = { at: '2026-09-18T11:00:00Z', status: 'failed', sources: { aws_production: 'available', aws_development: 'available', openai: 'unavailable' } };
    await go(); await page.waitForFunction(() => document.querySelector('#total').textContent === '$11.56');
    assert.match(await page.locator('#state-notice').innerText(), /Daily refresh failed/);
    // Without prior OpenAI data, show AWS and withhold the combined total.
    Object.assign(payload.sources.openai, { status: 'unavailable', retrieved_at: null, daily: [] });
    payload.month_to_date.openai = null; payload.month_to_date.total = null;
    payload.daily.forEach(row => { row.openai = null; row.total = null; });
    await go(); await page.waitForFunction(() => document.querySelector('#aws').textContent === '$4.76');
    assert.equal(await page.locator('#total').innerText(), 'Unavailable');
    assert.equal(await page.locator('#openai').innerText(), 'Unavailable');
    await checkChart();
    // The first day of a month has no completed MTD days, not missing data.
    environment = 'development'; payload = structuredClone(fixtures.development);
    const end = '2026-09-01', start = '2026-08-02';
    payload.requested = { start, end_exclusive: end };
    payload.periods = { month_to_date: { start: end, end_exclusive: end }, last_30_days: { start, end_exclusive: end } };
    payload.published_at = payload.attempt.at = '2026-09-01T10:00:00Z';
    Object.values(payload.sources).forEach(source => { source.requested = payload.requested; });
    Object.values(payload.sources).forEach(source => {
      source.retrieved_at = payload.published_at;
      source.daily.forEach((row, i) => { row.date = new Date(Date.parse(start) + i * 86400000).toISOString().slice(0, 10); });
    });
    payload.daily.forEach((row, i) => { row.date = payload.sources.aws_development.daily[i].date; });
    payload.sources.aws_development.aws_services = payload.aws_services = [];
    payload.sources.aws_development.aws_environments = payload.aws_environments = [];
    payload.month_to_date = { aws: '0', openai: '0', total: '0' };
    await go(); await page.waitForFunction(() => document.querySelector('#aws').textContent === '$0.00');
    assert.match(await page.locator('#period-label').innerText(), /No completed days/);
    await checkChart();
    fail = true; await page.reload(); await page.waitForFunction(() => document.querySelector('#aws').textContent === 'Unavailable');
    assert.match(await page.locator('#state-notice').innerText(), /could not be loaded/);
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    console.log('PASS: routes, navigation, decimal reconciliation, chart/table agreement, credits, mobile, keyboard, stale, unavailable, environment rejection, and refresh retention.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
