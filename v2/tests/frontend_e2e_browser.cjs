// Credential-free user journeys through the real frontend; run with Playwright on NODE_PATH.
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { readFile, mkdir } = require('node:fs/promises');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '../agent');
  const output = path.resolve(__dirname, '../../test-results/frontend-e2e');
  const routing = /** @type {{handler(event: {request: {method: string, uri: string}}): {uri: string}}} */ ({});
  vm.runInNewContext(await readFile(path.join(root, 'public-report-routes.js'), 'utf8'), routing);
  /** @type {import('node:http').ServerResponse | undefined} */
  let stream;
  /** @type {string[]} */
  const messages = [];
  let failChat = false;
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url || '/', 'http://localhost').pathname;
    if (pathname === '/api/reset') { response.setHeader('content-type', 'application/json'); response.end('{}'); return; }
    if (pathname === '/api/chat') {
      let body = ''; for await (const chunk of request) body += chunk;
      messages.push(JSON.parse(body).message);
      if (failChat) { response.writeHead(503, { 'content-type': 'application/json' }).end('{}'); return; }
      stream = response;
      response.writeHead(200, { 'content-type': 'application/x-ndjson' });
      response.write('\n'); return;
    }
    if (pathname === '/costs.json' || pathname === '/evals.json') { response.writeHead(503).end(); return; }
    const uri = routing.handler({ request: { method: request.method || 'GET', uri: pathname } }).uri;
    const file = path.resolve(root, uri === '/' ? 'dev_chat.html' : uri === '/chat.mjs' ? 'public_chat.mjs' : uri.slice(1));
    if (!file.startsWith(root + path.sep)) { response.writeHead(404).end(); return; }
    try {
      response.setHeader('content-type', file.endsWith('.mjs') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html');
      // The separate map browser test covers the actual renderer, pins and failures.
      const body = file.endsWith('/commute-map.mjs') ? 'export function mountCommuteMap() { document.querySelector("#map-loading").hidden = true; }'
        : file.endsWith('.html') ? (await readFile(file, 'utf8')).replaceAll('${environment}', 'development') : await readFile(file);
      response.end(body);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(undefined)));
  const origin = `http://127.0.0.1:${/** @type {import('node:net').AddressInfo} */ (server.address()).port}`;
  const browser = await chromium.launch();
  /** @param {import('playwright').Page} page */
  const ready = page => page.locator('#chat[aria-busy="false"] #message:not([disabled])').waitFor();
  /** @param {import('playwright').Page} page */
  const noOverflow = async page => assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= node.clientWidth), 'No horizontal page overflow');
  /** @param {import('../agent/public_chat.mjs').PublicEvent} event */
  const emit = event => { assert.ok(stream); stream.write(JSON.stringify(event) + '\n'); };
  /** @param {string} name @param {{width: number, height: number}} viewport @param {(page: import('playwright').Page) => Promise<void>} run */
  const flow = async (name, viewport, run) => {
    const context = await browser.newContext({ viewport });
    await context.tracing.start({ screenshots: true, snapshots: true });
    const page = await context.newPage();
    /** @type {string[]} */
    const errors = [];
    /** @type {string[]} */
    const external = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== origin) { external.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
    try {
      await page.goto(origin); await ready(page);
      await run(page); assert.deepEqual(errors, []); assert.deepEqual(external, []);
      await context.tracing.stop(); console.log(`PASS: ${name}`);
    } catch (error) {
      await mkdir(output, { recursive: true });
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
      await context.tracing.stop({ path: path.join(output, `${name}.zip`) });
      throw error;
    } finally { await context.close(); }
  };
  try {
    await flow('desktop-starter-stream-reset', { width: 1440, height: 900 }, async page => {
      for (const font of ['system-ui', '"DejaVu Sans", sans-serif']) {
        const style = await page.addStyleTag({ content: `body { font-family: ${font}; }` });
        for (const selector of ['h1', '.project-evidence', '#chat', '.map-panel']) {
          const box = await page.locator(selector).boundingBox(); assert.ok(box);
          assert.ok(box.y >= 0 && box.y + box.height <= 901, `${selector} fits the first desktop screen with ${font}`);
        }
      await style.evaluate(node => node.parentNode?.removeChild(node));
      }
      await noOverflow(page);
      const sent = page.waitForResponse(response => response.url().endsWith('/api/chat'));
      await page.locator('[data-prompt-index="1"]').click(); await sent;
      assert.equal(messages.at(-1), 'How much take-home pay would I have after commuting from Leesburg to Washington on Mondays and Fridays, leaving at 8:30 AM and returning at 5:30 PM for 96 days a year, on a $130,000 gross annual salary?');
      assert.equal(await page.locator('#chat button[type="submit"]').isDisabled(), true);
      assert.equal(await page.locator('#reset').isDisabled(), true);
      emit({ type: 'tool', index: 0, label: 'Checking supported pricing', status: 'running' });
      await page.locator('.activities [data-status="running"]').waitFor();
      emit({ type: 'text', text: 'Reviewing the commute evidence.' });
      await page.getByText('Reviewing the commute evidence.', { exact: true }).waitFor();
      emit({ type: 'tool', index: 0, label: 'Checked supported pricing', status: 'completed' });
      emit({ type: 'answer', text: '**Historical estimate:** $2,400 per year.', blocked: false });
      assert.ok(stream); stream.end(); await ready(page);
      assert.equal(await page.locator('.answer strong').innerText(), 'Historical estimate:');
      assert.equal(await page.locator('.activities [data-status="completed"]').count(), 1);
      await page.locator('#reset').click(); await ready(page);
      assert.equal(await page.locator('#transcript').innerText(), '');
      assert.equal(await page.locator('#starter-wrap').isVisible(), true);
    });
    await flow('shared-theme-and-navigation', { width: 1440, height: 900 }, async page => {
      const palette = () => page.locator('html').evaluate(node => {
        const style = /** @type {Window} */ (node.ownerDocument.defaultView).getComputedStyle(node);
        return ['--ink', '--blue', '--paper'].map(name => style.getPropertyValue(name).trim());
      });
      const expected = await palette(); assert.deepEqual(expected, ['#20332f', '#087f83', '#f7f8f4']);
      for (const href of ['/cost-dashboard', '/eval-dashboard', '/', '/faq.html', '/']) {
        await page.locator(`${href === '/faq.html' ? '.footer-links' : '.nav-links'} a[href="${href}"]`).click();
        await page.waitForURL(origin + href);
        assert.deepEqual(await palette(), expected);
        assert.deepEqual(await page.locator('.nav-links a').allTextContents(), ['Chat', 'Cost', 'Evaluation results']);
        if (href === '/cost-dashboard') { await page.getByText('No valid billing snapshot', { exact: true }).waitFor(); assert.equal(await page.locator('#total').innerText(), 'Unavailable'); }
        if (href === '/eval-dashboard') { await page.getByText('No verified snapshot could be loaded. No scores are shown.', { exact: true }).waitFor(); assert.equal(await page.locator('#metrics').innerText(), ''); }
        if (href === '/faq.html') { assert.equal(await page.locator('.faq-list section').count(), 10); await page.locator('.contents a[href="#map-title"]').click(); await page.waitForURL(origin + '/faq.html#map-title'); }
        if (href === '/') await ready(page);
        await noOverflow(page);
      }
    });
    await flow('mobile-keyboard-long-answer-and-failure', { width: 390, height: 844 }, async page => {
      const count = messages.length;
      await page.locator('#message').fill('Estimate my commute.');
      await page.locator('#message').press('Shift+Enter');
      assert.equal(await page.locator('#message').inputValue(), 'Estimate my commute.\n');
      assert.equal(messages.length, count);
      const sent = page.waitForResponse(response => response.url().endsWith('/api/chat'));
      await page.locator('#message').press('Enter'); await sent;
      await page.locator('#chat[aria-busy="true"]').waitFor();
      const answer = '## Your historical estimate\n\n' + 'A longer explanation of route evidence, assumptions, and annual commute costs.\n\n'.repeat(18) + '`' + 'long-route-evidence-'.repeat(40) + '`';
      emit({ type: 'answer', text: answer, blocked: false }); assert.ok(stream); stream.end(); await ready(page);
      assert.equal(messages.at(-1), 'Estimate my commute.');
      assert.equal(await page.locator('.answer h2').innerText(), 'Your historical estimate');
      assert.equal(await page.locator('.answer p').count(), 19); await noOverflow(page);
      failChat = true; await page.locator('#message').fill('Try another route.');
      await page.locator('#message').press('Enter');
      await page.locator('.answer.error').waitFor(); await ready(page);
      assert.equal(await page.locator('.answer.error').innerText(), 'TollChat is temporarily unavailable. Please try again.');
      assert.equal(await page.locator('#reset').isEnabled(), true); await noOverflow(page);
    });
  } finally { await browser.close(); server.closeAllConnections(); server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
