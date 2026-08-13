import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";

const answer = `## Route and fares

- Dumfries → Westpark Drive — **I-95/395 Express Lanes: $4.25**
  - VDOT observed at: 8/8/2026 10:00 AM ET

## Calculation

\`$4.25\` = **$4.25**

## Final price

| Type | Price |
| --- | ---: |
| Toll | **$4.25** |

1. Verify the estimate.
2. Drive safely.

> Estimates can change.

---

*Estimate only.*`;

test.beforeEach(async ({ page }) => {
  await page.route("**/api/reset", (route) => route.fulfill({ json: { ok: true } }));
});

const enableChat = async (page, assistantAnswer = answer, includeTool = true) => {
  const requests = [];
  const recordRequest = (route) => {
    const payload = route.request().postData();
    requests.push({ payload, hash: route.request().headers()["x-amz-content-sha256"] });
  };
  await page.route("**/api/chat", (route) => {
    recordRequest(route);
    const events = [
      ...(includeTool ? [{ type: "tool", index: 0, label: "Checking tolls", status: "completed" }] : []),
      { type: "answer", text: assistantAnswer, blocked: false },
    ];
    return route.fulfill({
      contentType: "application/x-ndjson",
      body: `${events.map(JSON.stringify).join("\n")}\n`,
    });
  });
  await page.route("**/api/reset", (route) => {
    recordRequest(route);
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto("/preview.html");
  await expect(page.locator("#message")).toBeEnabled();
  return requests;
};

test("renders streamed assistant Markdown and signs public POST bodies", async ({ page }) => {
  const requests = await enableChat(page);
  await page.locator("#message").fill("**Dumfries** <img src=x onerror=alert(1)>");
  await page.getByRole("button", { name: "Price trip" }).click();

  const user = page.locator(".user-turn");
  const assistant = page.locator(".assistant-answer").last();
  await expect(user).toHaveText("**Dumfries** <img src=x onerror=alert(1)>");
  await expect(user.locator("strong, img")).toHaveCount(0);
  await expect(assistant.getByRole("heading", { name: "Route and fares" })).toBeVisible();
  await expect(assistant.locator("strong").last()).toHaveText("$4.25");
  await expect(assistant.locator("table")).toBeVisible();
  await expect(assistant.locator("code")).toHaveText("$4.25");
  await expect(assistant.locator("ol li")).toHaveCount(2);
  await expect(assistant.locator("blockquote")).toHaveText("Estimates can change.");
  await expect(assistant.locator("hr")).toHaveCount(1);
  await expect(assistant.locator("em")).toHaveText("Estimate only.");

  await page.getByRole("button", { name: "New chat" }).click();
  await expect.poll(() => requests.length).toBe(3);
  for (const request of requests) {
    expect(request.hash).toBe(createHash("sha256").update(request.payload).digest("hex"));
    expect(JSON.parse(request.payload)).not.toHaveProperty("session_id");
  }
  expect(await page.evaluate(() => sessionStorage.getItem("tollchat-session"))).toBeNull();
});

test("expired ownership clears the transcript without replaying the message", async ({ page }) => {
  let chats = 0;
  await page.route("**/api/chat", (route) => {
    chats += 1;
    return route.fulfill({
      status: 401,
      headers: { "set-cookie": "__Host-tollchat-session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict" },
      json: { error: { code: "session_expired", message: "Your chat expired. Please send your question again." } },
    });
  });
  await page.goto("/preview.html");
  await page.locator("#message").fill("Price my trip");
  await page.getByRole("button", { name: "Price trip" }).click();

  await expect(page.locator(".user-turn")).toHaveCount(0);
  await expect(page.locator(".assistant-answer")).toHaveText("Your chat expired. Please send your question again.");
  expect(chats).toBe(1);
});

test("browser tab handoff rotates instead of silently merging chats", async ({ context, page }) => {
  const calls = [];
  await page.route("**/api/reset", (route) => {
    calls.push("first-reset");
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto("/preview.html");
  await expect(page.locator("#message")).toBeEnabled();

  const second = await context.newPage();
  await second.route("**/api/reset", (route) => {
    calls.push("second-reset");
    return route.fulfill({ json: { ok: true } });
  });
  await second.route("**/api/chat", (route) => {
    calls.push("second-chat");
    return route.fulfill({
      contentType: "application/x-ndjson",
      body: '{"type":"answer","text":"Fresh","blocked":false}\n',
    });
  });
  await second.goto("/preview.html");

  await expect(second.locator("#message")).toBeDisabled();
  await expect(second.locator(".assistant-answer")).toHaveText("TollChat is open in another tab.");
  await page.close();
  await second.reload();
  await expect(second.locator("#message")).toBeEnabled();
  await second.locator("#message").fill("new tab");
  await second.getByRole("button", { name: "Price trip" }).click();
  await expect(second.locator(".assistant-answer").last()).toHaveText("Fresh");
  expect(calls).toEqual(["first-reset", "second-reset", "second-chat"]);
});

test("failed resets preserve the transcript", async ({ page }) => {
  let privateResets = 0;
  await page.route("**/api/reset", (route) => {
    privateResets += 1;
    return privateResets === 1
      ? route.fulfill({ json: { ok: true } })
      : route.fulfill({
          status: 409,
          json: { error: { code: "session_busy", message: "Wait for the current response to finish." } },
        });
  });
  await page.goto("/preview.html");
  await page.locator("#transcript").evaluate((node) => {
    const turn = document.createElement("p");
    turn.className = "user-turn";
    turn.textContent = "keep me";
    node.append(turn);
  });
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator(".user-turn")).toHaveText("keep me");
  await expect(page.locator(".assistant-answer").last()).toHaveText("Wait for the current response to finish.");
});

test("an expired cookie is a successful page-load rotation", async ({ page }) => {
  await page.route("**/api/reset", (route) => route.fulfill({
    status: 401,
    headers: { "set-cookie": "__Host-tollchat-session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict" },
    json: { error: { code: "session_expired", message: "Your chat expired. Please send your question again." } },
  }));

  await page.goto("/preview.html");
  await expect(page.locator("#message")).toBeEnabled();
});

test("an expired cookie is a successful user reset", async ({ page }) => {
  let privateResets = 0;
  await page.route("**/api/reset", (route) => {
    privateResets += 1;
    return privateResets === 1
      ? route.fulfill({ json: { ok: true } })
      : route.fulfill({
          status: 401,
          json: { error: { code: "session_expired", message: "Your chat expired." } },
        });
  });
  await page.goto("/preview.html");
  await page.locator("#transcript").evaluate((node) => {
    const turn = document.createElement("p");
    turn.className = "user-turn";
    turn.textContent = "clear me";
    node.append(turn);
  });
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator("#transcript")).toBeEmpty();
});

test("private preview presents source-backed pricing with official verification links", async ({ page }) => {
  await page.goto("/preview.html");

  await expect(page).toHaveTitle("TollChat: Toll prices grounded in public records");
  await expect(page.getByText("Open beta · Source-backed toll records", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Plan with prices grounded in public records." })).toBeVisible();
  await expect(page.locator("header .lede")).toHaveText(
    "TollChat reconstructs supported Northern Virginia trips from VDOT-published dynamic prices and committed 2-axle E-ZPass rate tables for the Dulles roads. Dulles rates are hand-transcribed from operator pages and cross-checked against other public sources; every result shows the toll components and arithmetic used."
  );
  const evaluationNote = page.locator("header .evaluation-note");
  await expect(evaluationNote).toContainText("TollChat uses GPT-5.6 Luna");
  await expect(evaluationNote).toContainText(
    "In our 3,400-response frozen hallucination battery, it did not fabricate a toll price—but it did make other mistakes."
  );
  await expect(evaluationNote.getByRole("link", { name: "Read the limits" })).toHaveAttribute(
    "href",
    "/faq.html#hallucinations-title"
  );

  const sources = page.getByRole("navigation", { name: "Official pricing sources" });
  const expectedSources = [
    ["95/395/495 Express Lanes", "https://www.expresslanes.com/map-your-trip/"],
    ["I-66 Inside the Beltway", "https://vai66tolls.com/"],
    ["Dulles Toll Road", "https://www.dullestollroad.com/toll-rates-electronic-payment-and-pay-plate"],
    ["Dulles Greenway", "https://www.dullesgreenway.com/toll-calculator/"],
  ];
  for (const [name, href] of expectedSources) {
    const link = sources.getByRole("link", { name });
    await expect(link).toHaveAttribute("href", href);
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("referrerpolicy", "no-referrer");
  }

  await expect(page.locator("header").getByRole("link", { name: "TollChat CI status" })).toHaveCount(0);
  const footer = page.locator("footer");
  const badge = footer.getByRole("link", { name: "TollChat CI status" });
  await expect(badge).toHaveAttribute(
    "href",
    "https://github.com/rhprasad0/nova-toll-budget-agent/actions/workflows/ci.yml"
  );
  await expect(badge.locator("img")).toHaveAttribute(
    "src",
    "https://github.com/rhprasad0/nova-toll-budget-agent/actions/workflows/ci.yml/badge.svg"
  );
  await expect(badge).toHaveAttribute("referrerpolicy", "no-referrer");
  await expect(badge).toHaveAttribute("target", "_blank");
  await expect(badge).toHaveAttribute("rel", "noopener noreferrer");

  await expect(footer).toContainText("Found a bug or have another comment? Email contact@tollchat.ai.");
  await expect(footer.getByRole("link", { name: "contact@tollchat.ai" })).toHaveAttribute(
    "href",
    "mailto:contact@tollchat.ai"
  );
  await expect(footer.getByRole("link", { name: "GitHub", exact: true })).toHaveCount(0);
  const terms = footer.getByRole("link", { name: "VDOT SmarterRoads terms" });
  await expect(terms).toHaveAttribute(
    "href",
    "https://smarterroads.vdot.virginia.gov/termsOfService"
  );
  await expect(terms).toHaveAttribute("target", "_blank");
  await expect(terms).toHaveAttribute("rel", "noopener noreferrer");
  await expect(footer).toContainText("not affiliated with the Virginia Department of Transportation");
  await expect(footer).toContainText("as is and as available");
  await expect(footer).toContainText("may be inaccurate, delayed, changed, or unavailable");
  await expect(footer).toContainText("TollChat uses VDOT’s public toll pricing data.");
  await expect(footer).not.toContainText("and we’re fans");
  await expect(footer).toContainText("behavior may change, and no availability commitment is offered");
  await expect(footer).toContainText(
    "TollChat reports recorded VDOT prices and committed 2-axle E-ZPass Dulles rate tables, not future toll quotes. Verify current dynamic prices with the relevant operator before travel."
  );
  await expect(footer).not.toContainText("Estimates only.");
});

test("pricing FAQ explains freshness, route oracles, and the unpriced junction", async ({ page }) => {
  await page.goto("/preview.html");

  const faqEntry = page.locator("footer > .footer-faq");
  await expect(faqEntry).toBeVisible();
  await expect(faqEntry.getByRole("link", { name: "Pricing FAQ" })).toHaveAttribute(
    "href",
    "/faq.html"
  );
  await expect(faqEntry).toContainText("Data freshness, route oracles, and known coverage gaps.");

  await page.goto("/faq.html");
  await expect(page).toHaveTitle("Pricing FAQ · TollChat");
  await expect(page.getByRole("heading", { name: "How TollChat prices a trip." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Where do TollChat prices come from?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Why can TollChat differ from an operator site?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "How does the route oracle work?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Why is part of the I-95 ↔ I-495 junction unpriced?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Does TollChat hallucinate?" })).toBeVisible();

  const main = page.locator("main");
  await expect(main).toContainText("59,217 aligned comparisons matched exactly");
  await expect(main).toContainText("validates transport and time alignment, not independent toll-price accuracy");
  await expect(main).toContainText("six-minute intervals with a measured 1–4-minute source delay");
  await expect(main).toContainText("preceding VDOT capture until the next poll");
  await expect(main).not.toContainText("one capture behind VA66Tolls");
  await expect(main).toContainText("hand-transcribed 2-axle E-ZPass rate tables");
  await expect(main).toContainText("Exit 16 directional rule");
  await expect(main).toContainText("3,400 frozen, tool-disabled responses");
  await expect(main).toContainText("no dollar amount absent from the supplied toll evidence");
  await expect(main).toContainText("invented one observation time");
  await expect(main).toContainText("omitted required components, totals, or partial-price disclosures");
  await expect(main).toContainText("601 multi-leg responses still require manual semantic review");
  await expect(main).toContainText("More hallucination evaluations are planned");
  await expect(main).toContainText("weekday-only peak windows");
  await expect(main).toContainText("committed, read-only route map");
  await expect(main).toContainText("public maps and explicitly curated connector facts");
  await expect(main).toContainText("price lookup keys");
  await expect(main).toContainText("does not generate prices");
  await expect(main).toContainText("Edsall or Franconia-Springfield");
  await expect(main).toContainText("I-495 Near Braddock Road");
  await expect(main).toContainText("known toll total");
  await expect(main).toContainText("not a complete operator-issued fare");

  const expectedLinks = [
    ["95/395/495 Express Lanes", "https://www.expresslanes.com/map-your-trip/"],
    ["I-66 Inside the Beltway", "https://vai66tolls.com/"],
    ["Dulles Toll Road", "https://www.dullestollroad.com/toll-rates-electronic-payment-and-pay-plate"],
    ["Dulles Greenway", "https://www.dullesgreenway.com/toll-calculator/"],
  ];
  for (const [name, href] of expectedLinks) {
    await expect(main.getByRole("link", { name })).toHaveAttribute("href", href);
  }
  await expect(main.getByRole("link", { name: "Read the technical evidence" })).toHaveAttribute(
    "href",
    /docs\/oracle-findings\.md#9-vdot-republishes-transurbans-price-on-a-10-minute-delay$/
  );

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("footer carries the privacy notice and composer requests a latest price", async ({ page }) => {
  await page.goto("/preview.html");

  const notice = page.locator("footer #privacy-notice");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("retained in AWS for 30 days");
  await expect(notice).toContainText("OpenAI also processes and stores response data for at least 30 days");
  await expect(notice).toContainText("Do not submit personal, confidential, payment, credential, or unnecessarily precise location information");
  await expect(page.locator("#message")).toHaveAttribute("placeholder", "Latest price from Dumfries to Tysons");
  await expect(page.locator("#message")).not.toHaveAttribute("aria-describedby", "privacy-notice");
});

test("hostile Markdown stays inert while HTTPS links remain accessible", async ({ page }) => {
  await enableChat(page, `# Safety

<script>window.markdownAttack = true</script>
<style>body { display: none }</style>
<iframe srcdoc="<script>window.markdownAttack = true</script>"></iframe>
<img src=x onerror="window.markdownAttack = true">
![remote](https://example.com/tracker.png)
[unsafe](javascript:window.markdownAttack=true)
[data](data:text/html,boom)
[relative](/admin)
[](https://example.com/empty)
[   ](https://example.com/whitespace)
[&#x200B;](https://example.com/zero-width)
[safe documentation](https://www.vdot.virginia.gov/)

**unterminated emphasis

> A blockquote

---

\`\`\`text
${"x".repeat(300)}
\`\`\``, false);
  await page.locator("#message").fill("test");
  await page.getByRole("button", { name: "Price trip" }).click();

  const assistant = page.locator(".assistant-answer").last();
  await expect(assistant.locator("script, style, iframe, img")).toHaveCount(0);
  expect(await page.evaluate(() => window.markdownAttack)).toBeUndefined();
  await expect(assistant).toContainText("<script>window.markdownAttack = true</script>");
  await expect(assistant).toContainText("**unterminated emphasis");
  await expect(assistant.locator("a")).toHaveCount(4);
  for (const slug of ["empty", "whitespace", "zero-width"]) {
    const url = `https://example.com/${slug}`;
    await expect(assistant.locator(`a[href="${url}"]`)).toHaveText(url);
  }
  const link = assistant.getByRole("link", { name: "safe documentation" });
  await expect(link).toHaveAttribute("href", "https://www.vdot.virginia.gov/");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await link.focus();
  await expect(link).toBeFocused();
  await expect(assistant.locator("pre")).toHaveCSS("overflow-x", "auto");
});

test("private preview renders streamed assistant Markdown safely", async ({ page }) => {
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body: `${JSON.stringify({
        type: "answer",
        text: "## Fare\n\n**$4.25** <script>window.previewAttack=true</script> ![tracker](https://example.com/a.png)",
        blocked: false,
      })}\n`,
    })
  );
  await page.goto("/preview.html");
  await page.locator("#message").fill("Price my trip");
  await page.getByRole("button", { name: "Price trip" }).click();

  const answer = page.locator(".assistant-answer");
  await expect(answer.getByRole("heading", { name: "Fare" })).toBeVisible();
  await expect(answer.locator("strong")).toHaveText("$4.25");
  await expect(answer.locator("script, img")).toHaveCount(0);
  expect(await page.evaluate(() => window.previewAttack)).toBeUndefined();
});

test("private preview submits with Enter and keeps Shift+Enter as a newline", async ({ page }) => {
  let requests = 0;
  let signedRequest;
  await page.route("**/api/chat", (route) => {
    requests += 1;
    signedRequest = {
      payload: route.request().postData(),
      hash: route.request().headers()["x-amz-content-sha256"],
    };
    return route.fulfill({
      contentType: "application/x-ndjson",
      body: `${JSON.stringify({ type: "answer", text: "Done", blocked: false })}\n`,
    });
  });
  await page.goto("/preview.html");

  await page.locator("#message").fill("First line");
  await page.locator("#message").press("Shift+Enter");
  await page.locator("#message").type("Second line");
  await expect(page.locator("#message")).toHaveValue("First line\nSecond line");
  expect(requests).toBe(0);

  await page.locator("#message").press("Enter");
  await expect(page.locator(".user-turn")).toHaveText("First line\nSecond line");
  await expect(page.locator(".assistant-answer")).toHaveText("Done");
  expect(requests).toBe(1);
  expect(signedRequest.hash).toBe(
    createHash("sha256").update(signedRequest.payload).digest("hex")
  );
});

test("private preview blocks submission while a new chat is resetting", async ({ page }) => {
  let finishReset;
  let resets = 0;
  const resetPending = new Promise((resolve) => { finishReset = resolve; });
  await page.route("**/api/reset", async (route) => {
    resets += 1;
    if (resets === 1) return route.fulfill({ json: { ok: true } });
    await resetPending;
    await route.fulfill({ status: 204 });
  });
  await page.goto("/preview.html");

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator("form")).toHaveAttribute("aria-busy", "true");
  await expect(page.locator("#message")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Price trip" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "New chat" })).toBeDisabled();

  finishReset();
  await expect(page.locator("form")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#message")).toBeEnabled();
});

test("open-beta coverage map stays interactive and direction-aware", async ({ page }) => {
  await page.route("https://tiles.openfreemap.org/styles/dark", (route) =>
    route.fulfill({ json: { version: 8, sources: {}, layers: [] } })
  );
  await Promise.all([
    page.waitForRequest((request) => {
      const url = new URL(request.url());
      return url.pathname.endsWith("/assets/coverage-map-v2.mjs");
    }),
    page.goto("/preview.html"),
  ]);

  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "data:,");
  await expect(page.getByRole("region", { name: /Interactive TollChat coverage map/ })).toBeVisible();
  await expect(page.locator(".map-legend")).toContainText("Unlabelled ramps serve both directions.");
  await expect(page.locator(".preview-map-pin")).toHaveCount(82);
  await expect(page.locator(".landmark-map-pin")).toHaveCount(3);
  await expect(page.locator(".preview-map-pin").first()).toHaveCSS("isolation", "isolate");
  await expect(page.locator(".preview-map-pin[data-direction]")).toHaveCount(20);
  await expect(page.locator(".ramp-badge")).toHaveCount(20);
  await expect(page.locator("#directional-ramps")).toHaveCount(0);
  await expect(page.locator(".maplibregl-ctrl-zoom-in")).toHaveCount(1);
  await expect(page.locator("#route-filters button")).toHaveCount(6);
  await expect(page.locator("#route-filters button:enabled")).toHaveCount(6);
  await expect(page.locator("#reset-map")).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Read the limits" })).toBeFocused();
  for (const name of [
    "95/395/495 Express Lanes",
    "I-66 Inside the Beltway",
    "Dulles Toll Road",
    "Dulles Greenway",
  ]) {
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name })).toBeFocused();
  }
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "New chat" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip map and ask a question" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#message")).toBeFocused();
  expect(await page.locator(".preview-map-pin").evaluateAll((pins) =>
    pins.every((pin) => pin.tagName === "BUTTON" && pin.tabIndex === 0 &&
      pin.hasAttribute("aria-label"))
  )).toBe(true);
  expect(await page.locator(".preview-map-pin").evaluateAll((pins) => {
    const labels = pins.map((pin) => pin.getAttribute("aria-label"));
    return new Set(labels).size === labels.length;
  })).toBe(true);
  await expect(page.getByRole("button", { name: /95\/395 Express Lanes — I-95 Near Cardinal Drive: NB ENTRY only/ })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /I-66 — I-66 West: serves both directions/ })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Landmark — Dulles International Airport" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Landmark — Reagan National Airport" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Landmark — Washington, DC" })).toHaveCount(1);

  await page.getByRole("button", { name: "I-66", exact: true }).click();
  await expect(page.getByRole("button", { name: "I-66", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".preview-map-pin:visible")).toHaveCount(17);
  await expect(page.locator(".landmark-map-pin:visible")).toHaveCount(3);
  await page.getByRole("button", { name: "Landmark — Reagan National Airport" }).click();
  await expect(page.locator("#map-detail")).toContainText("Geographic reference only. Not a supported toll-road entry or exit.");
  await page.getByRole("button", { name: /I-495 S: serves both directions/ }).focus();
  await page.getByRole("button", { name: /I-495 N: EB ENTRY only/ }).focus();
  await expect(page.locator("#map-detail")).toContainText("EB entry only. 1 supported node (2)");

  await page.getByRole("button", { name: /I-66 West: serves both directions/ }).focus();
  await expect(page.locator("#map-detail")).toContainText("Serves both directions.");
  await page.getByRole("button", { name: "Reset coverage" }).click();
  await expect(page.locator(".preview-map-pin:visible")).toHaveCount(82);
  await expect(page.locator("#map-detail")).toContainText("Coverage break");

  const landmarksInsideMap = () => page.evaluate(() => {
    const map = document.querySelector("#coverage-map").getBoundingClientRect();
    return [...document.querySelectorAll(".landmark-map-pin")].every((pin) => {
      const bounds = pin.getBoundingClientRect();
      const x = bounds.left + bounds.width / 2;
      const y = bounds.top + bounds.height / 2;
      return x >= map.left && x <= map.right && y >= map.top && y <= map.bottom;
    });
  });
  await page.getByRole("button", { name: "Greenway", exact: true }).click();
  await expect.poll(landmarksInsideMap).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(landmarksInsideMap).toBe(true);
});

test("private 95/395 geometry stops at the Van Dorn ramp", async ({ page }) => {
  await page.goto("/preview.html");
  const geometry = await page.evaluate(async () => {
    const { coveragePins, routeData, routeDataForMode } = await import("/assets/coverage-map-v2.mjs");
    const i95Lines = (data) => data.features.find(
      (feature) => feature.properties.facility === "i95"
    ).geometry.coordinates;
    const eastOfVanDorn = (line) => line.every(
      ([longitude, latitude]) => longitude > -77.1 && latitude < 38.81
    );
    const publicLines = i95Lines(routeData);
    const previewData = routeDataForMode("preview");
    const previewLines = i95Lines(previewData);

    return {
      publicUnchanged: routeDataForMode("interactive") === routeData,
      publicEastFragments: publicLines.filter(eastOfVanDorn).length,
      previewEastFragments: previewLines.filter(eastOfVanDorn).length,
      publicLineCount: publicLines.length,
      previewLineCount: previewLines.length,
      previewStarts: previewLines.map(([start]) => start),
      hasVanDornPin: coveragePins.some(
        (pin) => pin.label === "I-495/I-95 Near Van Dorn Street"
      ),
    };
  });

  expect(geometry.publicUnchanged).toBe(true);
  expect(geometry.publicEastFragments).toBe(8);
  expect(geometry.previewEastFragments).toBe(0);
  expect(geometry.previewLineCount).toBe(geometry.publicLineCount - 8);
  expect(geometry.previewStarts).toContainEqual([-77.153219, 38.793384]);
  expect(geometry.previewStarts).toContainEqual([-77.154508, 38.793504]);
  expect(geometry.hasVanDornPin).toBe(true);
});

test("private preview stacks map before transcript on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/preview.html");

  const header = await page.locator("header").boundingBox();
  const map = await page.locator(".map-panel").boundingBox();
  const frame = await page.locator(".map-frame").boundingBox();
  const detail = await page.locator("#map-detail").boundingBox();
  const transcript = await page.locator("#transcript").boundingBox();
  const reset = await page.locator("#reset-map").boundingBox();
  expect(header.y + header.height).toBeLessThanOrEqual(map.y);
  expect(frame.y + frame.height).toBeLessThanOrEqual(detail.y);
  expect(detail.y + detail.height).toBeLessThanOrEqual(transcript.y);
  expect(reset.x + reset.width).toBeLessThanOrEqual(390);
  await expect(page.locator("form")).toHaveCSS("position", "static");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
