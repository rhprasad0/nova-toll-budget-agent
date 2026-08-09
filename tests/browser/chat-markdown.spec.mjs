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
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
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
  await page.goto("/");
  await expect(page.locator("#tollchat-chat")).toBeVisible();
  return requests;
};

test("renders streamed assistant Markdown and signs public POST bodies", async ({ page }) => {
  const requests = await enableChat(page);
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
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
  await page.route("**/api/chat", (route) => {
    chats += 1;
    return route.fulfill({
      status: 401,
      headers: { "set-cookie": "__Host-tollchat-session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict" },
      json: { error: { code: "session_expired", message: "Your chat expired. Please send your question again." } },
    });
  });
  await page.goto("/");
  await page.locator("#chat-input").fill("Price my trip");
  await page.locator("#chat-form").getByRole("button", { name: "Send" }).click();

  await expect(page.locator(".chat-message.user")).toHaveCount(0);
  await expect(page.locator(".chat-message.agent")).toHaveText("Your chat expired. Please send your question again.");
  expect(chats).toBe(1);
});

test("browser tab handoff rotates instead of silently merging chats", async ({ context, page }) => {
  const calls = [];
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
  await page.route("**/api/reset", (route) => {
    calls.push("first-reset");
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto("/");
  await expect(page.locator("#chat-input")).toBeEnabled();

  const second = await context.newPage();
  await second.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
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
  await second.goto("/");

  await expect(second.locator("#chat-input")).toBeDisabled();
  await expect(second.locator("#chat-status")).toHaveText("TollChat is open in another tab.");
  await page.close();
  await second.reload();
  await expect(second.locator("#chat-input")).toBeEnabled();
  await second.locator("#chat-input").fill("new tab");
  await second.getByRole("button", { name: "Send" }).click();
  await expect(second.locator(".chat-message.agent").last()).toHaveText("Fresh");
  expect(calls).toEqual(["first-reset", "second-reset", "second-chat"]);
});

test("failed resets preserve the public and private transcripts", async ({ page }) => {
  let publicResets = 0;
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
  await page.route("**/api/reset", (route) => {
    publicResets += 1;
    return publicResets === 1
      ? route.fulfill({ json: { ok: true } })
      : route.fulfill({
          status: 409,
          json: { error: { code: "session_busy", message: "Wait for the current response to finish." } },
        });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator(".chat-message.agent")).toHaveText("Where are you entering and exiting?");
  await expect(page.locator("#chat-status")).toHaveText("Wait for the current response to finish.");

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
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
  await page.route("**/api/reset", (route) => route.fulfill({
    status: 401,
    headers: { "set-cookie": "__Host-tollchat-session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict" },
    json: { error: { code: "session_expired", message: "Your chat expired. Please send your question again." } },
  }));

  await page.goto("/");
  await expect(page.locator("#chat-input")).toBeEnabled();
  await page.goto("/preview.html");
  await expect(page.locator("#message")).toBeEnabled();
});

test("an expired cookie is a successful user reset", async ({ page }) => {
  await page.route("**/api/config", (route) =>
    route.fulfill({ json: { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 } })
  );
  let publicResets = 0;
  await page.route("**/api/reset", (route) => {
    publicResets += 1;
    return publicResets === 1
      ? route.fulfill({ json: { ok: true } })
      : route.fulfill({
          status: 401,
          json: { error: { code: "session_expired", message: "Your chat expired." } },
        });
  });
  await page.goto("/");
  await page.locator("#chat-messages").evaluate((node) => {
    const turn = document.createElement("p");
    turn.className = "chat-message user";
    turn.textContent = "clear me";
    node.append(turn);
  });
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.locator(".chat-message.user")).toHaveCount(0);
  await expect(page.locator(".chat-message.agent")).toHaveText("Where are you entering and exiting?");

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
  expect(await page.evaluate(() => performance.getEntriesByType("resource").some((entry) => {
    const url = new URL(entry.name);
    return url.pathname.endsWith("/assets/coverage-map-v1.mjs") && url.searchParams.get("v") === "2";
  }))).toBe(true);
  await expect(page.getByRole("region", { name: /Interactive TollChat coverage map/ })).toBeVisible();
  await expect(page.locator(".map-legend")).toContainText("Unlabelled ramps serve both directions.");
  await expect(page.locator(".preview-map-pin")).toHaveCount(82);
  await expect(page.locator(".preview-map-pin").first()).toHaveCSS("isolation", "isolate");
  await expect(page.locator(".preview-map-pin[data-direction]")).toHaveCount(20);
  await expect(page.locator(".ramp-badge")).toHaveCount(20);
  await expect(page.locator("#directional-ramps")).toHaveCount(0);
  await expect(page.locator(".maplibregl-ctrl-zoom-in")).toHaveCount(1);
  await expect(page.locator("#route-filters button")).toHaveCount(6);
  await expect(page.locator("#route-filters button:enabled")).toHaveCount(6);
  await expect(page.locator("#reset-map")).toBeEnabled();
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

  await page.getByRole("button", { name: "I-66", exact: true }).click();
  await expect(page.getByRole("button", { name: "I-66", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".preview-map-pin:visible")).toHaveCount(17);
  await page.getByRole("button", { name: /I-495 S: serves both directions/ }).click();
  await page.getByRole("button", { name: /I-495 N: EB ENTRY only/ }).click();
  await expect(page.locator("#map-detail")).toContainText("EB entry only. 1 supported node (2)");

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
