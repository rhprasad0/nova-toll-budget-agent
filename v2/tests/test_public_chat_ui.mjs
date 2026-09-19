/** @typedef {import("../agent/public_chat.mjs").PublicEvent} PublicEvent */
/** @typedef {import("../agent/public_chat.mjs").ResponseError} ResponseError */
/** @typedef {{tagName: string, className: string, textContent: string, innerHTML: string, children: MockElement[], dataset: DOMStringMap, append(...children: MockElement[]): void}} MockElement */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import {
  applyEvent,
  consumeNdjson,
  post,
  runRequest,
  shouldSubmitOnEnter,
} from "../agent/public_chat.mjs";

/** @returns {MockElement} */
const element = (tagName = "div") => ({
  tagName,
  className: "",
  textContent: "",
  innerHTML: "",
  children: [],
  dataset: {},
  append(...children) { this.children.push(...children); },
});

const turn = () => ({
  activities: /** @type {HTMLElement} */ (/** @type {unknown} */ (element("ol"))),
  answer: element("div"),
  items: new Map(),
  // The DOM fake implements precisely the operations applyEvent consumes.
  createElement: /** @type {(tag: string) => HTMLElement} */ (/** @type {unknown} */ (element)),
});

/** @param {...string} events */
const stream = (...events) => new ReadableStream({
  start(controller) {
    for (const event of events) controller.enqueue(new TextEncoder().encode(event));
    controller.close();
  },
});

test("posts the exact proxy body with the CloudFront payload hash", async () => {
  const originalFetch = globalThis.fetch;
  /** @type {{path: RequestInfo | URL, body: string, headers: Record<string, string>} | undefined} */
  let request;
  globalThis.fetch = async (path, options) => {
    request = /** @type {{path: RequestInfo | URL, body: string, headers: Record<string, string>}} */ ({ path, ...options });
    return new Response();
  };
  try {
    await post("/api/chat", { message: "Price it" });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.ok(request);
  assert.equal(request.path, "/api/chat");
  assert.equal(request.body, '{"message":"Price it"}');
  assert.equal(request.headers["content-type"], "application/json");
  assert.match(request.headers["x-amz-content-sha256"], /^[a-f0-9]{64}$/);
  const expected = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(request.body));
  assert.equal(
    request.headers["x-amz-content-sha256"],
    Buffer.from(expected).toString("hex"),
  );
});

test("renders deployed tool and terminal events", () => {
  const view = turn();
  applyEvent(view, {
    type: "tool", index: 0, label: "Checking current toll price", status: "running",
  });
  applyEvent(view, {
    type: "tool", index: 0, label: "Checking current toll price", status: "completed",
  });
  applyEvent(view, { type: "answer", text: "The toll is **$4.25**.", blocked: false });

  assert.equal(view.activities.children.length, 1);
  assert.equal(view.activities.children[0].children[1].textContent, "Completed");
  assert.match(view.answer.innerHTML, /<strong>\$4\.25<\/strong>/);
});

test("parses one terminal NDJSON event and rejects private envelopes", async () => {
  /** @type {PublicEvent[]} */
  const seen = [];
  await consumeNdjson(stream(
    '{"type":"tool","index":0,"label":"Checking current toll price","status":"running"}\n',
    '{"type":"answer","text":"Done","blocked":false}\n',
  ), (event) => seen.push(event));
  assert.deepEqual(seen.map(({ type }) => type), ["tool", "answer"]);

  await assert.rejects(
    () => consumeNdjson(stream('{"type":"event","sequence":0,"event":{}}\n'), () => {}),
    /invalid stream event/,
  );
  await assert.rejects(
    () => consumeNdjson(stream(
      '{"type":"answer","text":"Done","blocked":false}\n',
      '{"type":"error","code":"agent_unavailable","message":"Unavailable"}\n',
    ), () => {}),
    /event after terminal/,
  );
});

test("session expiry takes the restart path and failures stay generic", async () => {
  /** @type {PublicEvent[]} */
  const events = [];
  /** @type {ResponseError[]} */
  const expired = [];
  const error = /** @type {ResponseError} */ (new Error("Your chat expired."));
  error.code = "session_expired";
  await runRequest(
    async () => { throw error; },
    (event) => events.push(event),
    () => {},
    (value) => expired.push(value),
  );
  assert.deepEqual(events, /** @type {PublicEvent[]} */ ([]));
  assert.deepEqual(expired, [error]);

  await runRequest(
    async () => { throw new Error("secret network detail"); },
    (event) => events.push(event),
    () => {},
  );
  const last = events.at(-1);
  assert.ok(last && last.type === "error");
  assert.equal(last.code, "agent_unavailable");
  assert.doesNotMatch(last.message, /secret/);
});

test("keyboard submission preserves newline and composition behavior", () => {
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, false), true);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: true, isComposing: false }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: true }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, true), false);
});

test("public API gate allows only the deployed operations", async () => {
  const source = await readFile(new URL("../agent/public-api-gate.js", import.meta.url), "utf8");
  const context = /** @type {{gate(event: {request: {method: string, uri: string}}): {statusCode?: number, uri?: string}}} */ ({});
  vm.runInNewContext(`${source}\nthis.gate = handler;`, context);

  for (const [method, uri] of [
    ["GET", "/api/config"],
    ["POST", "/api/chat"],
    ["POST", "/api/reset"],
  ]) {
    assert.deepEqual(context.gate({ request: { method, uri } }), { method, uri });
  }
  const blocked = context.gate({ request: { method: "GET", uri: "/api/chat" } });
  assert.equal(blocked.statusCode, 404);
});

test("public report routes rewrite toll directories with or without trailing slashes", async () => {
  const source = await readFile(new URL("../agent/public-report-routes.js", import.meta.url), "utf8");
  const context = /** @type {{rewrite(event: {request: {method: string, uri: string}}): {uri: string}}} */ ({});
  vm.runInNewContext(`${source}\nthis.rewrite = handler;`, context);

  for (const [uri, expected] of [
    ["/tolls/i95-i495/", "/tolls/i95-i495/index.html"],
    ["/tolls/i95-i495/origin/destination/", "/tolls/i95-i495/origin/destination/index.html"],
    ["/tolls/i95-i495/origin/destination", "/tolls/i95-i495/origin/destination/index.html"],
    ["/tolls/i95-i495/origin/destination/report.json", "/tolls/i95-i495/origin/destination/report.json"],
    ["/eval-dashboard", "/evals.html"],
    ["/eval-dashboard/", "/evals.html"],
    ["/eval-dashboard-other", "/eval-dashboard-other"],
    ["/robots.txt", "/robots.txt"],
    ["/sitemap.xml", "/sitemap.xml"],
    ["/assets/favicon.png", "/assets/favicon.png"],
    ["/api/config", "/api/config"],
  ]) {
    assert.equal(context.rewrite({ request: { method: "GET", uri } }).uri, expected);
  }
});

test("release changes show the restart message without replaying the prompt", async () => {
  let calls = 0;
  /** @type {string[]} */
  const messages = [];
  await runRequest(async () => {
    calls += 1;
    const error = /** @type {ResponseError} */ (new Error("The application was updated. Start a new conversation."));
    error.code = "session_expired";
    throw error;
  }, () => assert.fail("must use restart path"), () => {}, (error) => messages.push(error.message));
  assert.equal(calls, 1);
  assert.deepEqual(messages, ["The application was updated. Start a new conversation."]);
});
