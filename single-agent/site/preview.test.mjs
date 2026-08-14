import assert from "node:assert/strict";
import test from "node:test";

import { applyEvent, consumeNdjson, runRequest, shouldSubmitOnEnter } from "./preview.mjs";

const element = (tagName = "div") => ({
  tagName,
  className: "",
  textContent: "",
  innerHTML: "",
  children: [],
  dataset: {},
  append(...children) { this.children.push(...children); },
  setAttribute(name, value) { this[name] = value; },
});

const turn = () => ({
  activities: element("ol"),
  answer: element("p"),
  items: new Map(),
  createElement: element,
});

test("tool events render in order and the answer stays distinct", () => {
  const view = turn();

  applyEvent(view, { type: "tool", index: 0, label: "Planning toll route", status: "running" });
  applyEvent(view, { type: "tool", index: 1, label: "Checking I-495 tolls", status: "running" });
  applyEvent(view, { type: "tool", index: 0, label: "Planning toll route", status: "completed" });
  applyEvent(view, { type: "answer", text: "The toll is $8.10.", blocked: false });

  assert.equal(view.activities.children.length, 2);
  assert.equal(view.activities.children[0].children[0].textContent, "Planning toll route");
  assert.equal(view.activities.children[0].children[1].textContent, "Completed");
  assert.equal(view.activities.children[1].children[0].textContent, "Checking I-495 tolls");
  assert.match(view.answer.innerHTML, /<p>The toll is \$8\.10\.<\/p>/);
  assert.equal(view.answer.className, "assistant-answer");
});

test("assistant Markdown renders safely while errors remain literal", () => {
  const view = turn();

  applyEvent(view, {
    type: "answer",
    text: "## Fare\n\n**$4.25** <script>window.attack=true</script> ![tracker](https://example.com/a.png)",
    blocked: false,
  });

  assert.match(view.answer.innerHTML, /<h2>Fare<\/h2>/);
  assert.match(view.answer.innerHTML, /<strong>\$4\.25<\/strong>/);
  assert.doesNotMatch(view.answer.innerHTML, /<script|<img/i);
  assert.match(view.answer.innerHTML, /&lt;script&gt;/);

  applyEvent(view, { type: "error", code: "agent_unavailable", message: "**literal**" });
  assert.equal(view.answer.textContent, "**literal**");
});

test("failed tools expose text and status semantics without removing the composer", async () => {
  const view = turn();
  const busy = [];

  await runRequest(
    async (onEvent) => {
      onEvent({ type: "tool", index: 0, label: "Checking Dulles tolls", status: "running" });
      throw new Error("network detail");
    },
    (event) => applyEvent(view, event),
    (value) => busy.push(value),
  );

  assert.deepEqual(busy, [true, false]);
  assert.equal(view.activities.children[0].children[1].textContent, "Failed");
  assert.equal(view.activities.children[0].dataset.status, "failed");
  assert.match(view.answer.textContent, /temporarily unavailable/i);
  assert.doesNotMatch(view.answer.textContent, /network detail/);
});

test("session expiry uses the restart path without rendering a generic failure", async () => {
  const events = [];
  const expired = [];
  const error = new Error("Your chat expired. Please send your question again.");
  error.code = "session_expired";

  await runRequest(
    async () => { throw error; },
    (event) => events.push(event),
    () => {},
    (value) => expired.push(value),
  );

  assert.equal(events.length, 0);
  assert.deepEqual(expired, [error]);
});

test("NDJSON parser handles split chunks and rejects unknown envelopes", async () => {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('{"type":"tool","index":0,'));
      controller.enqueue(encoder.encode('"label":"Planning toll route","status":"running"}\n'));
      controller.enqueue(encoder.encode('{"type":"answer","text":"Done","blocked":false}\n'));
      controller.close();
    },
  });
  const seen = [];

  await consumeNdjson(stream, (event) => seen.push(event));
  assert.deepEqual(seen.map((event) => event.type), ["tool", "answer"]);

  const invalid = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('{"type":"reasoning","text":"secret"}\n'));
      controller.close();
    },
  });
  await assert.rejects(() => consumeNdjson(invalid, () => {}), /invalid stream event/);
});

test("NDJSON parser requires exactly one terminal event", async () => {
  const encoder = new TextEncoder();
  const stream = (...events) => new ReadableStream({
    start(controller) {
      for (const event of events) controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
      controller.close();
    },
  });

  await assert.rejects(
    () => consumeNdjson(stream({ type: "tool", index: 0, label: "Planning toll route", status: "running" }), () => {}),
    /missing terminal event/,
  );
  await assert.rejects(
    () => consumeNdjson(stream(
      { type: "answer", text: "Done", blocked: false },
      { type: "error", code: "agent_unavailable", message: "Unavailable" },
    ), () => {}),
    /event after terminal/,
  );
});

test("Enter submits unless the user wants a newline or is still composing", () => {
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, false), true);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: true, isComposing: false }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: true }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 229 }, false), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, true), false);
  assert.equal(shouldSubmitOnEnter({ key: "a", shiftKey: false, isComposing: false }, false), false);
});
