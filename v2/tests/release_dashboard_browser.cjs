// Exercise the real static documents, route rewrite, and release-prefixed assets without JavaScript.
const assert = require("node:assert/strict");
const { createServer } = require("node:http");
const { mkdir, readFile } = require("node:fs/promises");
const path = require("node:path");
const vm = require("node:vm");
const { chromium } = require("playwright");

(async () => {
  const root = path.resolve(__dirname, "../agent");
  const output = path.resolve(__dirname, "../../test-results/release-dashboard");
  const routing = /** @type {{handler(event: {request: {method: string, uri: string}}): {uri: string}}} */ ({});
  vm.runInNewContext(await readFile(path.join(root, "public-report-routes.js"), "utf8"), routing);
  /** @type {string[]} */
  const missing = [];
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url || "/", "http://localhost").pathname;
    const uri = routing.handler({ request: { method: request.method || "GET", uri: pathname } }).uri;
    const name = uri === "/" ? "dev_chat.html" : uri.replace(/^\/releases\/local\//, "/").slice(1);
    const file = path.resolve(root, name);
    if (!file.startsWith(root + path.sep)) { response.writeHead(404).end(); return; }
    try {
      const source = await readFile(file);
      response.setHeader("content-type", file.endsWith(".css") ? "text/css" : file.endsWith(".png") ? "image/png" : "text/html");
      response.end(file.endsWith(".html")
        ? source.toString().replaceAll('"/assets/', '"/releases/local/assets/').replaceAll("${environment}", "development")
        : source);
    } catch {
      missing.push(uri);
      response.writeHead(404).end();
    }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", () => resolve(undefined)));
  const address = /** @type {import("node:net").AddressInfo} */ (server.address());
  const origin = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    for (const source of ["/", "/faq.html", "/cost-dashboard", "/eval-dashboard"]) {
      await page.goto(origin + source);
      const link = page.getByRole("navigation", { name: "Project pages" }).getByRole("link", { name: "Release", exact: true });
      await link.click();
      assert.equal(new URL(page.url()).pathname, "/release-dashboard");
      await page.getByRole("heading", { name: "A measured step forward." }).waitFor();
    }
    assert.equal(await page.locator('nav a[aria-current="page"]').innerText(), "Release");
    assert.equal(await page.locator("script").count(), 0);
    assert.match(await page.locator(".score-grid").innerText(), /269\/300/);
    assert.match(await page.locator(".verdict").innerText(), /includes zero/);
    assert.equal(await page.locator("#family-results tbody tr").count(), 8);
    assert.match(await page.locator(".regression").innerText(), /23\/30.*76\.7%/s);
    assert.equal(await page.getByRole("img", { name: /Observed gain of 4.0/ }).count(), 1);
    assert.equal(await page.getByRole("meter").count(), 8);
    await page.locator("#methodology summary").focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#methodology[open]").count(), 1);
    assert.match(await page.locator("#methodology").innerText(), /10,000 bootstrap draws/);
    await page.keyboard.press("Enter");
    await page.goto(origin + "/release-dashboard/");
    assert.equal((await page.getByRole("link", { name: "Prompt 2.3.15 / renderer 1.0.2 ↓", exact: true }).getAttribute("href")), "#prompt-2-3-15");
    await mkdir(output, { recursive: true });
    await page.screenshot({ path: path.join(output, "desktop.png"), fullPage: true });
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const size = await page.locator("body").boundingBox();
      assert.ok(size && size.width <= width, `body overflows at ${width}px`);
      for (const selector of [".score-grid", ".verdict-panel", ".contracts", ".nav-links"]) {
        const box = await page.locator(selector).boundingBox();
        assert.ok(box && box.x >= 0 && box.x + box.width <= width, `${selector} overflows at ${width}px`);
      }
      await page.screenshot({ path: path.join(output, `mobile-${width}.png`), fullPage: true });
    }
    assert.deepEqual(missing, []);
    console.log("Release dashboard: navigation, no-JavaScript rendering, keyboard disclosure, charts, and mobile layouts passed.");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(() => resolve(undefined)));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
