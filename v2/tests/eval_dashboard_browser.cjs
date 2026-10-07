// Playwright executes these callback bodies in a browser, across the Node type boundary.
// Run with Playwright available on NODE_PATH.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.clock.install({ time: new Date("2026-09-15T21:24:00Z") });
    /** @type {string[]} */
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const scenarios = Array.from({ length: 6 }, (_, i) => ({
      id: String(i),
      title: `Scenario ${i}`,
      description: "A real pricing question",
      route: "Origin → Destination",
      tag: "I-95",
    }));
    const snapshot = {
      schema_version: 1,
      environment: "development",
      generated_at: "2026-09-15T21:20:00Z",
      scenarios,
      runs: [
        {
          window_id: "south",
          scenario_id: "0",
          scheduled_at: "2026-09-15T18:17:00Z",
          status: "passed",
          evidence: {
            policy_version: /** @type {string | undefined} */ ("scheduled-critical-v1"),
            checks: ["ToolCallCount", "Completeness", "Correctness"].map(
              (name) => ({
                name,
                passed: true,
                reason: "Evidence supports the answer.",
              }),
            ),
            turns: [
              {
                user: "<img src=x onerror=alert(1)>",
                assistant: "The observed toll is $12.",
                tools: [{ result: { total_usd: 12 } }],
              },
            ],
          },
        },
      ],
      schedule: [
        {
          window_id: "south",
          scenario_id: "0",
          scheduled_at: "2026-09-15T20:00:00Z",
        },
        {
          window_id: "north",
          scenario_id: "1",
          scheduled_at: "2026-09-16T12:00:00Z",
        },
      ],
    };
    let data = snapshot,
      status = 200;
    await page.route("https://dashboard.test/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/evals.json")
        return route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(data),
        });
      const file = url.pathname === "/" ? "evals.html" : url.pathname.slice(1);
      const body = (
        await fs.readFile(path.join(__dirname, "../agent", file), "utf8")
      ).replace("${environment}", "development");
      return route.fulfill({
        body,
        contentType: file.endsWith(".css")
          ? "text/css"
          : file.endsWith(".mjs")
            ? "text/javascript"
            : "text/html",
      });
    });
    await page.goto("https://dashboard.test/");
    await page.locator(".scenario").first().waitFor();
    assert.equal(await page.locator(".scenario").count(), 6);
    assert.match(await page.locator("#metrics").innerText(), /1 of 1/);
    assert.equal(await page.locator(".scenario .overdue").count(), 1);
    await page.locator(".scenario summary").first().focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator(".scenario details[open]").count(), 1);
    assert.equal(await page.locator(".bubble img").count(), 0);
    assert.match(await page.locator(".bubble").first().innerText(), /<img/);
    assert.match(await page.locator(".scenario .tool-evidence").last().innerText(), /not recorded/);
    Object.assign(snapshot.runs[0].evidence, { model: "gpt-5.6-luna" });
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    await page.locator(".scenario summary").first().click();
    assert.match(await page.locator(".scenario .tool-evidence").last().innerText(), /gpt-5.6-luna/);
    Object.assign(snapshot.runs[0].evidence, { models: {
      application: {model: "deployed-model", reasoning_effort: "low", max_output_tokens: 2048},
      actor: {model: "gpt-6-luna", reasoning_effort: "low", max_output_tokens: 2048},
      judge: {model: "gpt-6-luna", reasoning_effort: "xhigh", max_output_tokens: 8192},
    } });
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    await page.locator(".scenario summary").first().click();
    const modelLabels = await page.locator(".scenario .tool-evidence").last().innerText();
    assert.match(modelLabels, /Application: deployed-model \(low reasoning\)/);
    assert.match(modelLabels, /Simulated user: gpt-6-luna \(low reasoning\)/);
    assert.match(modelLabels, /Judges: gpt-6-luna \(xhigh reasoning\)/);
    assert.doesNotMatch(modelLabels, /gpt-5.6-luna/);
    assert.match(modelLabels, /scheduled-critical-v1/);
    const legacyFailed = {
      ...snapshot.runs[0], scheduled_at: "2026-09-15T17:00:00Z", status: "failed",
      evidence: {...snapshot.runs[0].evidence, policy_version: undefined,
        checks: snapshot.runs[0].evidence.checks.map((check) => ({...check, passed: false})),
      },
    };
    data = {...snapshot, runs: [...snapshot.runs, legacyFailed]};
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    assert.match(await page.locator("#metrics").innerText(), /1 of 1/);
    assert.match(await page.locator("#shown").innerText(), /1 legacy graded runs/);
    assert.match(await page.locator("#history").innerText(), /Failed · Legacy grading/);
    const criticalFailed = {...legacyFailed, scheduled_at: "2026-09-15T16:00:00Z",
      evidence: {...legacyFailed.evidence, policy_version: "scheduled-critical-v1"},
    };
    data = {...snapshot, runs: [...snapshot.runs, legacyFailed, criticalFailed]};
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    assert.match(await page.locator("#metrics").innerText(), /1 of 2/);
    assert.match(await page.locator("#metrics").innerText(), /Critical failures\s+1/);
    data = snapshot;
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    await page.selectOption("#outcome", "error");
    assert.equal(await page.locator(".run").count(), 1);
    status = 503;
    await page.clock.runFor(60000);
    await page.waitForFunction(() => {
      const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
      return /** @type {HTMLElement & {textContent: string}} */ (browser.document.querySelector("#freshness"))
        .textContent.includes("Refresh failed");
    },
    );
    assert.match(await page.locator("#metrics").innerText(), /1 of 1/);
    status = 200;
    data = { ...snapshot, environment: "production" };
    await page.reload();
    await page.waitForFunction(() => {
      const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
      return /** @type {HTMLElement & {textContent: string}} */ (browser.document.querySelector("#freshness"))
        .textContent.includes("not available");
    },
    );
    assert.equal(await page.locator(".scenario").count(), 0);
    data = { ...snapshot, runs: [], schedule: [] };
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    assert.match(
      await page.locator("#metrics").innerText(),
      /No completed runs under the current policy/,
    );
    assert.doesNotMatch(await page.locator("#metrics").innerText(), /NaN|100%/);
    data = {...snapshot, runs: [legacyFailed]};
    await page.reload();
    await page.locator(".scenario").first().waitFor();
    assert.match(await page.locator("#metrics").innerText(), /No completed runs under the current policy/);
    assert.match(await page.locator("#history").innerText(), /Failed · Legacy grading/);
    for (const width of [320, 390, 820, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(
        await page.evaluate(
          () => {
      const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
      return browser.document.documentElement.scrollWidth <= browser.innerWidth;
    },
        ),
        `Overflow at ${width}`,
      );
    }
    assert.deepEqual(errors, []);
    console.log(
      "PASS: real snapshot rendering, missing runs, safe text, keyboard, refresh failure, environment isolation, empty state, responsive layout",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
