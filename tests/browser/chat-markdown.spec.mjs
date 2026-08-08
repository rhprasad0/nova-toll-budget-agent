import { expect, test } from "@playwright/test";

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

const enableChat = async (page, assistantAnswer = answer) => {
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
  await page.route("**/api/chat", (route) =>
    route.fulfill({ json: { answer: assistantAnswer } })
  );
  await page.goto("/");
  await expect(page.locator("#tollchat-chat")).toBeVisible();
};

test("renders assistant Markdown and keeps user input literal", async ({ page }) => {
  await enableChat(page);
  await page.locator("#chat-input").fill("**Dumfries** <img src=x onerror=alert(1)>");
  await page.locator("#chat-form").getByRole("button", { name: "Send" }).click();

  const user = page.locator(".chat-message.user");
  const assistant = page.locator(".chat-message.agent").last();
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
\`\`\``);
  await page.locator("#chat-input").fill("test");
  await page.locator("#chat-form").getByRole("button", { name: "Send" }).click();

  const assistant = page.locator(".chat-message.agent").last();
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

test("does not download the Markdown renderer when chat is disabled", async ({ page }) => {
  const rendererRequests = [];
  page.on("request", (request) => {
    if (request.url().includes("chat-markdown")) rendererRequests.push(request.url());
  });
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: false, maxMessageChars: 8000, maxTurns: 5 } })
  );

  await page.goto("/");

  await expect(page.locator("#tollchat-chat")).toBeHidden();
  expect(rendererRequests).toEqual([]);
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
  await page.getByRole("button", { name: "Estimate tolls" }).click();

  const answer = page.locator(".assistant-answer");
  await expect(answer.getByRole("heading", { name: "Fare" })).toBeVisible();
  await expect(answer.locator("strong")).toHaveText("$4.25");
  await expect(answer.locator("script, img")).toHaveCount(0);
  expect(await page.evaluate(() => window.previewAttack)).toBeUndefined();
});

test("private preview submits with Enter and keeps Shift+Enter as a newline", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/chat", (route) => {
    requests += 1;
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
});

test("private preview blocks submission while a new chat is resetting", async ({ page }) => {
  let finishReset;
  const resetPending = new Promise((resolve) => { finishReset = resolve; });
  await page.route("**/api/reset", async (route) => {
    await resetPending;
    await route.fulfill({ status: 204 });
  });
  await page.goto("/preview.html");

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator("form")).toHaveAttribute("aria-busy", "true");
  await expect(page.locator("#message")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Estimate tolls" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "New chat" })).toBeDisabled();

  finishReset();
  await expect(page.locator("form")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#message")).toBeEnabled();
});

test("shared coverage map stays interactive publicly and direction-aware privately", async ({ page }) => {
  await page.route("https://tiles.openfreemap.org/styles/dark", (route) =>
    route.fulfill({ json: { version: 8, sources: {}, layers: [] } })
  );
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: false, maxMessageChars: 8000, maxTurns: 5 } })
  );
  await page.goto("/");
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "data:,");
  await expect(page.locator(".map-pin")).toHaveCount(82);
  await expect(page.locator(".ramp-badge")).toHaveCount(0);
  await expect(page.locator(".maplibregl-ctrl-zoom-in")).toHaveCount(1);
  await expect(page.locator("#reset-map")).toBeEnabled();

  await page.goto("/preview.html");

  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "data:,");
  await expect(page.getByRole("region", { name: /Interactive TollChat coverage map/ })).toBeVisible();
  await expect(page.locator(".map-legend")).toContainText("Unlabelled ramps serve both directions.");
  await expect(page.locator(".preview-map-pin")).toHaveCount(82);
  await expect(page.locator(".preview-map-pin[data-direction]")).toHaveCount(20);
  await expect(page.locator(".ramp-badge")).toHaveCount(20);
  await expect(page.locator("#directional-ramps")).toHaveCount(0);
  await expect(page.locator(".maplibregl-ctrl-zoom-in")).toHaveCount(1);
  await expect(page.locator("#route-filters button")).toHaveCount(6);
  await expect(page.locator("#route-filters button:enabled")).toHaveCount(6);
  await expect(page.locator("#reset-map")).toBeEnabled();
  expect(await page.locator(".preview-map-pin").evaluateAll((pins) =>
    pins.every((pin) => pin.tagName === "BUTTON" && pin.tabIndex === 0 &&
      pin.hasAttribute("aria-label"))
  )).toBe(true);
  await expect(page.getByRole("button", { name: /I-95 Near Cardinal Drive: NB ENTRY only/ })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /I-66 West: serves both directions/ })).toHaveCount(1);

  await page.getByRole("button", { name: "I-66", exact: true }).click();
  await expect(page.getByRole("button", { name: "I-66", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".preview-map-pin:visible")).toHaveCount(17);
  await page.getByRole("button", { name: /I-495 N: EB ENTRY only/ }).focus();
  await expect(page.locator("#map-detail")).toContainText("EB entry only.");

  await page.getByRole("button", { name: /I-66 West: serves both directions/ }).focus();
  await expect(page.locator("#map-detail")).toContainText("Serves both directions.");
  await page.getByRole("button", { name: "Reset coverage" }).click();
  await expect(page.locator(".preview-map-pin:visible")).toHaveCount(82);
  await expect(page.locator("#map-detail")).toContainText("Coverage break");
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
