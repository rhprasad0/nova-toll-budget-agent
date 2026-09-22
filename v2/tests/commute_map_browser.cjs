// Run with: node tests/commute_map_browser.cjs (requires Playwright Chromium).
const assert = require("node:assert/strict");
const { createServer } = require("node:http");
const { readFile } = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const root = path.resolve(__dirname, "../agent");
  const { coverageCoordinates } = await import("../agent/assets/commute-map.mjs");
  /** @type {import("../agent/assets/commute-map.mjs").CoverageSnapshot} */
  const coverage = JSON.parse(await readFile(path.join(root, "assets/coverage-locations.json"), "utf8"));
  /** @type {import("../agent/assets/commute-map.mjs").EstimateSnapshot} */
  const estimates = JSON.parse(await readFile(path.join(root, "assets/commute-estimates.json"), "utf8"));
  const coordinatesByPoint = new Map(coverage.locations.flatMap((location) => (
    location.points.map(({ point_id: pointId }) => [pointId, coverageCoordinates(location)])
  )));
  const expectedCoordinates = {
    coverage: coverage.locations.map(coverageCoordinates),
    estimates: estimates.estimates.map((estimate) => (
      coordinatesByPoint.get(estimate.outbound.origin_point_id) || estimate.coordinates
    )),
  };
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url || "/", "http://localhost").pathname;
    if (pathname === "/api/reset") { response.setHeader("content-type", "application/json"); response.end("{}"); return; }
    if (pathname === "/chat.mjs") {
      response.setHeader("content-type", "text/javascript");
      response.end('import { mountCommuteMap } from "./assets/commute-map.mjs"; mountCommuteMap().then(map => { window.commuteMap = map; }).catch(() => {});');
      return;
    }
    const file = path.resolve(root, pathname === "/" ? "dev_chat.html" : pathname.slice(1));
    if (!file.startsWith(root + path.sep)) { response.writeHead(404).end(); return; }
    try {
      response.setHeader("content-type", file.endsWith(".mjs") ? "text/javascript"
        : file.endsWith(".css") ? "text/css" : file.endsWith(".html") ? "text/html" : "application/json");
      response.end(await readFile(file));
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", () => resolve(undefined)));
  const address = /** @type {import("node:net").AddressInfo} */ (server.address());
  const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
      /** @type {string[]} */
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      // Keep the real vendored renderer and local geography; only the external basemap is replaced.
      await page.route("https://tiles.openfreemap.org/**", route => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#eef2ef" } }] }),
      }));
      await page.goto(`http://127.0.0.1:${address.port}`);
      await page.locator(".estimate-pin").last().waitFor();
      await page.waitForFunction(() => {
        const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
        return browser.commuteMap?.isStyleLoaded();
      });
      assert.equal(await page.locator(".estimate-pin").count(), 4);
      assert.equal(await page.locator(".coverage-marker").count(), 103);
      assert.equal(await page.locator(".map-legend-item").count(), 6);
      assert.equal(await page.locator('.maplibregl-ctrl-attrib a[href="https://www.openstreetmap.org/copyright"]').count(), 1);
      assert.equal(await page.locator("#map-loading").isVisible(), false);
      assert.equal(await page.locator("#map-error").isVisible(), false);
      const geometry = await page.evaluate((expected) => {
        const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
        const frame = browser.commuteMap.getContainer().getBoundingClientRect();
        return {
          overflow: browser.document.documentElement.scrollWidth > browser.innerWidth,
          frame: { left: frame.left, top: frame.top, width: frame.width, height: frame.height },
          pins: [...browser.document.querySelectorAll(".estimate-pin")].map((pin, index) => {
            const rect = pin.getBoundingClientRect();
            const point = browser.commuteMap.project(expected.estimates[index]);
            const card = /** @type {Element} */ (pin.querySelector(".estimate-marker"));
            const pointer = browser.getComputedStyle(card, "::after");
            const side = parseFloat(pointer.height);
            const cardRect = card.getBoundingClientRect();
            const border = parseFloat(browser.getComputedStyle(card).borderBottomWidth);
            const tipY = pin.getAttribute("data-orientation") === "below"
              ? cardRect.top + border + parseFloat(pointer.top) + side / 2 - side * Math.SQRT1_2
              : cardRect.bottom - border - parseFloat(pointer.bottom) - side / 2 + side * Math.SQRT1_2;
            const price = /** @type {Element} */ (pin.querySelector("strong"));
            const label = /** @type {Element} */ (pin.querySelector(".estimate-marker > span"));
            return {
              dx: Math.abs(rect.left + rect.width / 2 - frame.left - point.x),
              dy: Math.abs(tipY - frame.top - point.y),
              priceSize: parseFloat(browser.getComputedStyle(price).fontSize),
              labelSize: parseFloat(browser.getComputedStyle(label).fontSize),
              inside: rect.left >= frame.left && rect.right <= frame.right && rect.top >= frame.top && rect.bottom <= frame.bottom,
              left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
            };
          }),
          casing: browser.commuteMap.getPaintProperty("toll-corridor-casing", "line-color"),
          accessDash: browser.commuteMap.getPaintProperty("toll-access-connections", "line-dasharray"),
          accessFilter: browser.commuteMap.getFilter("toll-access-connections"),
          mainlineFilter: browser.commuteMap.getFilter("toll-corridors"),
          rampFilter: browser.commuteMap.getFilter("toll-ramps"),
          overviewRamps: browser.commuteMap.queryRenderedFeatures({ layers: ["toll-ramps"] }).length,
          coverageErrors: [...browser.document.querySelectorAll(".coverage-marker")].map((pin, index) => {
            const rect = pin.getBoundingClientRect();
            const point = browser.commuteMap.project(expected.coverage[index]);
            return Math.hypot(rect.left + rect.width / 2 - frame.left - point.x,
              rect.top + rect.height / 2 - frame.top - point.y);
          }),
        };
      }, expectedCoordinates);
      assert.equal(geometry.overflow, false, "map must not create horizontal overflow");
      assert.equal(geometry.casing, "#ffffff");
      assert.deepEqual(geometry.accessDash, [2, 2]);
      assert.deepEqual(geometry.accessFilter, ["==", ["get", "role"], "access"]);
      assert.deepEqual(geometry.mainlineFilter, ["==", ["get", "role"], "mainline"]);
      assert.deepEqual(geometry.rampFilter, ["==", ["get", "role"], "ramp"]);
      assert.equal(geometry.overviewRamps, 0, "small ramps stay hidden at regional overview zoom");
      assert.ok(geometry.coverageErrors.every((error) => error <= 1), "coverage markers center on their snapped coordinates");
      for (const pin of geometry.pins) {
        assert.ok(pin.dx <= 1 && pin.dy <= 1, `pin tip must remain on its coordinate: ${JSON.stringify(pin)}`);
        assert.ok(pin.priceSize >= 18 && pin.labelSize >= 12, "estimate labels must stay readable");
        assert.ok(pin.inside, `estimate pin must fit inside the map at ${viewport.width}px: ${JSON.stringify({pin,frame:geometry.frame})}`);
      }
      for (let index = 0; index < geometry.pins.length; index++) {
        for (const other of geometry.pins.slice(index + 1)) {
          const pin = geometry.pins[index];
          assert.ok(pin.right <= other.left || other.right <= pin.left || pin.bottom <= other.top || other.bottom <= pin.top,
            `annual estimate pins must not overlap at ${viewport.width}px: ${JSON.stringify({ pin, other })}`);
        }
      }
      await page.locator(".estimate-pin").first().click();
      await page.waitForFunction(() => {
        const browser = /** @type {Window} */ (/** @type {unknown} */ (globalThis));
        const frame = /** @type {HTMLElement} */ (browser.document.querySelector("#commute-map"));
        const canvas = /** @type {HTMLCanvasElement} */ (frame.querySelector("canvas"));
        return frame.clientWidth === canvas.clientWidth && frame.clientHeight === canvas.clientHeight;
      });
      assert.equal(await page.locator('.estimate-pin[data-selected="true"]').count(), 1);
      assert.match(await page.locator("#map-detail").innerText(), /Historical annual estimate/i);
      assert.match(await page.locator("#map-detail").innerText(), /240 commute days/);
      assert.match(await page.locator("#map-detail").innerText(), /Estimate snapshot generated/);
      await page.locator("#reset-map").click();
      assert.equal(await page.locator('[data-selected="true"]').count(), 0);
      assert.match(await page.locator("#map-detail").innerText(), /Map guide/i);
      await page.locator('.coverage-marker[data-airport="true"]').first().focus();
      assert.match(await page.locator("#map-detail").innerText(), /Supported origin or destination/);
      await page.keyboard.press("Enter");
      assert.equal(await page.locator('.coverage-marker[data-selected="true"]').count(), 1);
      const springfield = coordinatesByPoint.get("i95:202NO");
      assert.ok(springfield);
      await page.evaluate((center) => {
        const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
        browser.commuteMap.jumpTo({ center, zoom: 14 });
      }, springfield);
      await page.waitForFunction(() => {
        const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
        return browser.commuteMap.queryRenderedFeatures({ layers: ["toll-ramps"] }).length > 0;
      });
      const zoomedPins = await page.evaluate((coordinates) => {
        const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
        const frame = browser.commuteMap.getContainer().getBoundingClientRect();
        return [...browser.document.querySelectorAll(".coverage-marker")].flatMap((pin, index) => {
          const point = browser.commuteMap.project(coordinates[index]);
          if (point.x < 0 || point.x > frame.width || point.y < 0 || point.y > frame.height) return [];
          const rect = pin.getBoundingClientRect();
          return [Math.hypot(rect.left + rect.width / 2 - frame.left - point.x,
            rect.top + rect.height / 2 - frame.top - point.y)];
        });
      }, expectedCoordinates.coverage);
      assert.ok(zoomedPins.length && zoomedPins.every((error) => error <= 1),
        "Springfield markers stay aligned to the ramps when zoomed in");
      if (viewport.width === 1440) {
        // Independent reviewed OSM anchors, not expectations derived from coverageCoordinates.
        for (const { id, coordinate } of [
          { id: "i495:180SO", coordinate: [-77.1835471, 38.9638971] }, // Node 292441942, southbound entry.
          { id: "i95:234NO", coordinate: [-77.48805564368462, 38.343591759540665] }, // Projection onto NB approach 1020591635.
        ]) {
          const entryIndex = coverage.locations.findIndex(({ points }) => points.some(({ point_id: pointId }) => pointId === id));
          assert.ok(entryIndex >= 0);
          await page.evaluate((center) => {
            const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
            browser.commuteMap.jumpTo({ center, zoom: 15 });
          }, coordinate);
          await page.waitForFunction(({ index, coordinate }) => {
            const browser = /** @type {Window & {commuteMap: import("../agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs").Map}} */ (/** @type {unknown} */ (globalThis));
            const frame = browser.commuteMap.getContainer().getBoundingClientRect();
            const pin = browser.document.querySelectorAll(".coverage-marker")[index].getBoundingClientRect();
            const point = browser.commuteMap.project(coordinate);
            return Math.hypot(pin.left + pin.width / 2 - frame.left - point.x,
              pin.top + pin.height / 2 - frame.top - point.y) <= 1;
          }, { index: entryIndex, coordinate });
        }
      }
      assert.deepEqual(errors, []);
      console.log(`Map rendering, anchoring, selection and layout ${viewport.width}x${viewport.height}: passed`);
      await page.close();
    }
    for (const failure of ["stalled", "invalid", "public-module", "dev-module"]) {
      const page = await browser.newPage();
      await page.clock.install();
      const moduleStall = failure.endsWith("-module");
      if (moduleStall) {
        await page.route("**/chat.mjs", async route => route.fulfill({
          contentType: "text/javascript",
          body: await readFile(path.join(root, failure === "public-module" ? "public_chat.mjs" : "dev_chat.mjs")),
        }));
      }
      await page.route(moduleStall ? "**/assets/commute-routes.mjs" : "**/assets/commute-estimates.json",
        route => failure === "invalid" ? route.fulfill({ contentType: "application/json", body: "{}" }) : undefined);
      await page.goto(`http://127.0.0.1:${address.port}`, { waitUntil: "domcontentloaded" });
      if (failure !== "invalid") await page.clock.runFor(12001);
      await page.locator("#map-error").waitFor();
      assert.equal(await page.locator("#map-loading").isVisible(), false);
      assert.equal(await page.locator("#reset-map").isDisabled(), true);
      console.log(`Map ${failure} startup shows fallback: passed`);
      await page.close();
    }
  } finally {
    await browser.close();
    server.closeAllConnections();
    server.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
