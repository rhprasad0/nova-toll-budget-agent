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
