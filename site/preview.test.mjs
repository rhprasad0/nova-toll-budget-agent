import assert from "node:assert/strict";
import test from "node:test";

import { applyEvent, consumeNdjson, runRequest } from "./preview.mjs";

const element = (tagName = "div") => ({
  tagName,
  className: "",
  textContent: "",
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
  assert.equal(view.answer.textContent, "The toll is $8.10.");
  assert.equal(view.answer.className, "assistant-answer");
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
