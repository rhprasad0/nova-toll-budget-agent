// Run with: node tests/public_chat_scroll_browser.cjs (requires Playwright Firefox/Chromium).
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { readFile } = require('node:fs/promises');
const path = require('node:path');
const { firefox, chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '../agent');
  /** @type {import('node:http').ServerResponse | undefined} */
  let stream;
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url || '/', 'http://localhost').pathname;
    if (pathname === '/api/reset') { response.end('{}'); return; }
    if (pathname === '/api/chat') {
      stream = response;
      response.setHeader('content-type', 'application/x-ndjson');
      response.flushHeaders();
      response.write("\n");
      return;
    }
    const file = path.resolve(root, pathname === '/' ? 'dev_chat.html'
      : pathname === '/chat.mjs' ? 'public_chat.mjs' : pathname.slice(1));
    if (!file.startsWith(root + path.sep)) { response.writeHead(404).end(); return; }
    try {
      response.setHeader('content-type', file.endsWith('.mjs') ? 'text/javascript'
        : file.endsWith('.html') ? 'text/html' : file.endsWith('.css') ? 'text/css' : 'application/octet-stream');
      // Retain the map layout without unrelated map rendering or network traffic.
      response.end(file.endsWith('/commute-map.mjs') ? 'export function mountCommuteMap() {}' : await readFile(file));
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(undefined)));
  const address = /** @type {import('node:net').AddressInfo} */ (server.address());
  try {
    for (const engine of [firefox, chromium]) {
      const browser = await engine.launch();
      try {
        for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
          for (const starter of [false, true]) {
            const page = await browser.newPage({ viewport });
            await page.goto(`http://127.0.0.1:${address.port}`);
            await page.waitForFunction(() => {
              const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
              return !/** @type {HTMLTextAreaElement} */ (browser.document.querySelector('#message')).disabled;
            });
            if (!starter) await page.locator('#message').fill('Explain the toll estimate.');
            await Promise.all([
              page.waitForResponse(response => response.url().endsWith('/api/chat')),
              page.locator(starter ? '[data-prompt-index="0"]' : '#chat button[type="submit"]').click(),
            ]);
            assert.equal(await page.locator('#chat button[type="submit"]').isDisabled(), true);
            assert.equal(await page.locator('#reset').isDisabled(), true);
            const position = () => page.evaluate(() => {
              const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
              return { y: browser.scrollY, bottom: /** @type {HTMLElement} */ (browser.document.querySelector('.assistant-turn')).getBoundingClientRect().bottom, height: browser.innerHeight };
            });
            let previous = await position();
            assert.ok(previous.bottom <= previous.height + 1, 'new turn must be visible, including starter prompts');
            /** @param {import('../agent/public_chat.mjs').PublicEvent} event */
            const emit = async event => {
              assert.ok(stream);
              stream.write(JSON.stringify(event) + '\n');
              if (event.type === 'tool') await page.waitForFunction(index => {
                const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
                return browser.document.querySelectorAll('.activities li').length === index + 1;
              }, event.index);
              else await page.waitForFunction(text => {
                const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
                return browser.document.querySelector('.answer')?.textContent?.replace(/\s+/g, ' ').trim() === text.replace(/\s+/g, ' ').trim();
              }, event.type === 'error' ? event.message : event.text);
            };
            await emit({ type: 'text', text: 'First approved text.' });
            assert.ok((await position()).y >= previous.y - 1, 'first text must not pull the page up');
            for (let index = 0; index < 6; index++) {
              await emit({ type: 'tool', index, label: 'Checking the route and current toll estimate', status: 'running' });
              const current = await position();
              assert.ok(current.bottom <= current.height + 1, 'tool growth must not disable following');
            }
            let text = '';
            for (let index = 0; index < 10; index++) {
              text += 'A paragraph explaining the toll estimate, assumptions, and limitations.\n\n';
              await emit({ type: 'text', text });
              const current = await position();
              assert.ok(current.bottom <= current.height + 1, `text growth must stay visible: step ${index}, ${JSON.stringify(current)}`);
            }
            await page.evaluate(() => {
              const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
              browser.scrollBy({ top: -300, behavior: 'instant' });
            });
            previous = await position();
            text += 'A final explanation and disclaimer.';
            await emit({ type: 'text', text });
            await emit({ type: 'answer', text, blocked: false });
            assert.ok(Math.abs((await position()).y - previous.y) <= 1, 'updates must preserve the reader position');
            assert.ok(stream);
            stream.end();
            console.log(`${engine.name()} ${browser.version()} ${viewport.width}x${viewport.height} ${starter ? 'starter' : 'composer'}: passed`);
            await page.close();
          }
        }
      } finally { await browser.close(); }
    }
  } finally { server.closeAllConnections(); server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
