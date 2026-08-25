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
  usageProofText,
} from "../agent/public_chat.mjs";

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
  activities: element("ol"),
  answer: element("div"),
  items: new Map(),
  createElement: element,
});

const stream = (...events) => new ReadableStream({
  start(controller) {
    for (const event of events) controller.enqueue(new TextEncoder().encode(event));
    controller.close();
  },
});

test("posts the exact proxy body with the CloudFront payload hash", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (path, options) => {
    request = { path, ...options };
    return { ok: true };
  };
  try {
    await post("/api/chat", { message: "Price it" });
  } finally {
    globalThis.fetch = originalFetch;
  }

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
  const events = [];
  const expired = [];
  const error = new Error("Your chat expired.");
  error.code = "session_expired";
  await runRequest(
    async () => { throw error; },
    (event) => events.push(event),
    () => {},
    (value) => expired.push(value),
  );
  assert.deepEqual(events, []);
  assert.deepEqual(expired, [error]);

  await runRequest(
    async () => { throw new Error("secret network detail"); },
    (event) => events.push(event),
    () => {},
  );
  assert.equal(events.at(-1).code, "agent_unavailable");
  assert.doesNotMatch(events.at(-1).message, /secret/);
});

test("keyboard submission preserves newline and composition behavior", () => {
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, false), true);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: true, isComposing: false }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: true }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, true), false);
});

test("public API gate allows only the deployed operations", async () => {
  const source = await readFile(new URL("../agent/public-api-gate.js", import.meta.url), "utf8");
  const context = {};
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
  const context = {};
  vm.runInNewContext(`${source}\nthis.rewrite = handler;`, context);

  for (const [uri, expected] of [
    ["/tolls/i95-i495/", "/tolls/i95-i495/index.html"],
    ["/tolls/i95-i495/origin/destination/", "/tolls/i95-i495/origin/destination/index.html"],
    ["/tolls/i95-i495/origin/destination", "/tolls/i95-i495/origin/destination/index.html"],
    ["/tolls/i95-i495/origin/destination/report.json", "/tolls/i95-i495/origin/destination/report.json"],
    ["/robots.txt", "/robots.txt"],
    ["/sitemap.xml", "/sitemap.xml"],
    ["/assets/favicon.png", "/assets/favicon.png"],
    ["/api/config", "/api/config"],
  ]) {
    assert.equal(context.rewrite({ request: { method: "GET", uri } }).uri, expected);
  }
});

test("usage proof accepts only current nonnegative cumulative snapshots", () => {
  const snapshot = {
    schema_version: 1,
    collection_started_on: "2026-08-24",
    as_of: "2026-08-25T05:15:00Z",
    engaged_sessions: 12,
    completed_responses: 34,
  };
  const now = Date.parse("2026-08-25T12:00:00Z");

  assert.equal(
    usageProofText(snapshot, now),
    "Since August 24, 2026, 12 counted anonymous chat sessions sent a message. TollChat completed 34 responses. Updated daily; last updated August 25, 2026.",
  );
  assert.equal(usageProofText({ ...snapshot, engaged_sessions: -1 }, now), null);
  assert.equal(usageProofText({ ...snapshot, engaged_sessions: 1.5 }, now), null);
  assert.equal(
    usageProofText({ ...snapshot, as_of: "2026-08-22T05:15:00Z" }, now),
    null,
  );
  assert.equal(usageProofText({}, now), null);
});
