// Run explicitly: node tests/deployed_chat_browser.cjs. Makes three real development AI calls.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

const ORIGIN = "https://dev.tollchat.ai";
const root = path.resolve(__dirname, "../agent");
const artifacts = path.resolve(__dirname, "../../test-results/deployed-chat");

(async () => {
  await fs.mkdir(artifacts, { recursive: true });
  const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15000);
  /** @type {string[]} */
  const errors = [];
  /** @type {{scenario: string, status: number, tools: number, answered: boolean}[]} */
  const results = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
    // Exercise this checkout's UI against the real same-origin development API.
    // Keep deployment headers on the document, including its actual CSP.
    await page.route(`${ORIGIN}/**`, async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname.startsWith("/api/")) return route.continue();
      const relative = pathname === "/" ? "dev_chat.html"
        : pathname === "/chat.mjs" ? "public_chat.mjs" : pathname.slice(1);
      const file = path.resolve(root, relative);
      if (!file.startsWith(root + path.sep)) return route.abort();
      const body = await fs.readFile(file);
      if (pathname === "/") {
        const response = await route.fetch();
        assert.equal(response.ok(), true, "deployed development page must be available");
        return route.fulfill({ response, body });
      }
      return route.fulfill({ body, contentType: file.endsWith(".mjs") ? "text/javascript"
        : file.endsWith(".css") ? "text/css" : file.endsWith(".png") ? "image/png" : "application/json" });
    });
    // The real renderer is covered separately; external tile availability is not an AI gate.
    await page.route("https://tiles.openfreemap.org/**", route => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#eef2ef" } }] }),
    }));
    const initialReset = page.waitForResponse(response => response.url() === `${ORIGIN}/api/reset`);
    await page.goto(ORIGIN, { waitUntil: "domcontentloaded" });
    assert.equal((await initialReset).ok(), true, "real development session must open");
    await page.locator('#chat[aria-busy="false"]').waitFor();

    /** @param {string} scenario @param {string} question @param {number} expectedTurns */
    const ask = async (scenario, question, expectedTurns) => {
      await page.locator("#message").fill(question);
      const responsePromise = page.waitForResponse(response => response.url() === `${ORIGIN}/api/chat`, { timeout: 75000 });
      await page.locator('#chat button[type="submit"]').click();
      const response = await responsePromise;
      assert.equal(response.ok(), true, `${scenario}: real AI request failed with HTTP ${response.status()}`);
      await page.locator('#chat[aria-busy="false"]').waitFor({ timeout: 75000 });
      // The UI validates streamed terminal events itself. Inspect the rendered result;
      // Chromium may discard the network body of an already-consumed streaming response.
      const completed = await page.locator('.assistant-turn').last()
        .locator('.activities [data-status="completed"]').filter({ hasText: 'Checking current toll price' }).count();
      assert.ok(completed > 0, `${scenario}: expected a completed current-price lookup`);
      assert.equal(await page.locator(".assistant-turn").count(), expectedTurns);
      assert.equal(await page.locator(".answer.error").count(), 0);
      assert.ok((await page.locator(".answer").last().innerText()).trim().length > 40);
      await page.screenshot({ path: path.join(artifacts, `${scenario}.png`), fullPage: true });
      results.push({ scenario, status: response.status(), tools: completed, answered: true });
      console.log(`Deployed development AI ${scenario}: passed`);
    };

    await ask("current-price", "What is the current toll from Leesburg to Washington via I-66, for a 2-axle vehicle with E-ZPass?", 1);
    await ask("follow-up", "What about starting from Reston Parkway instead, still to Washington via I-66?", 2);
    const resetResponse = page.waitForResponse(response => response.url() === `${ORIGIN}/api/reset`);
    await page.locator("#reset").click();
    assert.equal((await resetResponse).ok(), true, "real conversation reset must succeed");
    await page.locator('#chat[aria-busy="false"]').waitFor();
    assert.equal(await page.locator(".assistant-turn").count(), 0);
    assert.equal(await page.locator("#starter-wrap").isVisible(), true);
    await ask("fresh-conversation", "What is the current toll from Reston Parkway to Washington via I-66, for a 2-axle vehicle with E-ZPass?", 1);
    assert.deepEqual(errors, []);
  } catch (error) {
    await page.screenshot({ path: path.join(artifacts, "failure.png"), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    // Store only non-sensitive outcomes and screenshots. Browser traces can include session cookies.
    await fs.writeFile(path.join(artifacts, "results.json"), JSON.stringify(results, null, 2) + "\n");
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
