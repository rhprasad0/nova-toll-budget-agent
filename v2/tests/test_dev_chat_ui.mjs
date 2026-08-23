import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MAX_RAW_EVENT_LOG_CHARS,
  STARTER_PROMPTS,
  applyEvent,
  consumeNdjson,
  validStreamEvent,
} from "../agent/dev_chat.mjs";
import { renderAssistantMarkdown } from "../agent/assets/chat-markdown.mjs";
import {
  formatAnnualToll,
  validateEstimateSnapshot,
} from "../agent/assets/commute-map.mjs";

const commuteEstimates = JSON.parse(await readFile(
  new URL("../agent/assets/commute-estimates.json", import.meta.url),
  "utf8",
));

const stream = (...chunks) => new ReadableStream({
  start(controller) {
    for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
    controller.close();
  },
});

const fakeView = () => ({
  activities: { append() {} },
  answer: { classList: { add() {} }, innerHTML: "", textContent: "" },
  article: {
    scrolls: 0,
    scrollIntoView() { this.scrolls += 1; },
  },
  items: new Map(),
  raw: { textContent: "" },
  renderFrame: null,
  text: "",
});

test("consumes split NDJSON events through one terminal result", async () => {
  const seen = [];
  await consumeNdjson(stream(
    '{"type":"event","sequence":0,"event":{"data":"Hi 👋"},"text_',
    'delta":"Hi 👋"}\n{"type":"event","sequence":1,"event":{"result":{}},',
    '"final":{"text":"Hi 👋","metrics":{}}}\n',
  ), (event) => seen.push(event));

  assert.equal(seen.length, 2);
  assert.equal(seen[0].text_delta, "Hi 👋");
  assert.equal(seen[1].final.text, "Hi 👋");
});

test("rejects malformed and unterminated streams", async () => {
  await assert.rejects(() => consumeNdjson(stream("not json\n"), () => {}));
  await assert.rejects(
    () => consumeNdjson(
      stream('{"type":"event","sequence":0,"event":{}}\n'),
      () => {},
    ),
    /missing terminal event/,
  );
  assert.equal(validStreamEvent({ type: "event", sequence: -1, event: {} }), false);
});

test("bounds raw events and batches streamed Markdown into one animation frame", () => {
  const originalRequest = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  const frames = new Map();
  let nextFrame = 0;
  globalThis.requestAnimationFrame = (callback) => {
    const id = ++nextFrame;
    frames.set(id, callback);
    return id;
  };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);

  try {
    const oversized = fakeView();
    applyEvent(oversized, {
      type: "event",
      sequence: 0,
      event: { payload: "x".repeat(MAX_RAW_EVENT_LOG_CHARS * 2) },
    });
    assert.equal(oversized.raw.textContent.length, MAX_RAW_EVENT_LOG_CHARS);
    assert.match(oversized.raw.textContent, /^… older events omitted …\n/);

    const streaming = fakeView();
    applyEvent(streaming, {
      type: "event", sequence: 0, event: {}, text_delta: "Hello ",
    });
    applyEvent(streaming, {
      type: "event", sequence: 1, event: {}, text_delta: "**driver** 👋",
    });
    assert.equal(frames.size, 1);
    assert.equal(streaming.answer.innerHTML, "");
    assert.equal(streaming.article.scrolls, 0);

    const [frameId, render] = frames.entries().next().value;
    frames.delete(frameId);
    render();
    assert.match(streaming.answer.innerHTML, /Hello <strong>driver<\/strong> 👋/);
    assert.equal(streaming.article.scrolls, 1);

    applyEvent(streaming, {
      type: "event", sequence: 2, event: {}, text_delta: " partial",
    });
    assert.equal(frames.size, 1);
    applyEvent(streaming, {
      type: "event",
      sequence: 3,
      event: {},
      final: { text: "## Final 👋", metrics: {} },
    });
    assert.equal(frames.size, 0);
    assert.match(streaming.answer.innerHTML, /<h2>Final 👋<\/h2>/);
    assert.equal(streaming.article.scrolls, 2);

    applyEvent(streaming, {
      type: "event", sequence: 4, event: {}, text_delta: " stale",
    });
    assert.equal(frames.size, 1);
    applyEvent(streaming, {
      type: "error", sequence: 5, message: "Request failed",
    });
    assert.equal(frames.size, 0);
    assert.equal(streaming.answer.textContent, "Request failed");
    assert.equal(streaming.article.scrolls, 3);
  } finally {
    if (originalRequest) globalThis.requestAnimationFrame = originalRequest;
    else delete globalThis.requestAnimationFrame;
    if (originalCancel) globalThis.cancelAnimationFrame = originalCancel;
    else delete globalThis.cancelAnimationFrame;
  }
});

test("renders supported Markdown and emoji while hostile content stays inert", () => {
  const html = renderAssistantMarkdown(
    "## Price 👋\n\n**$4.25** [safe](https://example.com) "
      + "[bad](javascript:alert(1)) <img src=x onerror=alert(1)> ![alt](https://x.test/x.png)",
  );

  assert.match(html, /<h2>Price 👋<\/h2>/);
  assert.match(html, /<strong>\$4\.25<\/strong>/);
  assert.match(html, /href="https:\/\/example\.com"/);
  assert.doesNotMatch(html, /href="javascript:|<img/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /alt/);
});

test("starter prompts are complete enough to submit without clarification", () => {
  assert.deepEqual(STARTER_PROMPTS, [
    "What is the current price from Dumfries to Washington?",
    "What is my take-home pay commuting from Leesburg to Washington on Monday and Friday, "
      + "leaving at 8:30 AM and returning at 5:30 PM, for 96 commute days per year and a "
      + "$130,000 gross annual salary?",
  ]);
});

test("checked-in estimate snapshot contains the four approved Washington commutes", () => {
  const snapshot = validateEstimateSnapshot(commuteEstimates);

  assert.equal(snapshot.schema_version, 1);
  assert.equal(snapshot.destination, "Washington, DC");
  assert.deepEqual(snapshot.assumptions.weekdays, [
    "monday", "tuesday", "wednesday", "thursday", "friday",
  ]);
  assert.equal(snapshot.assumptions.outbound_departure_time, "08:30:00");
  assert.equal(snapshot.assumptions.return_departure_time, "17:30:00");
  assert.equal(snapshot.assumptions.planned_annual_commute_days, 240);
  assert.deepEqual(
    snapshot.estimates.map(({ id }) => id),
    ["dumfries", "springfield-franconia", "leesburg", "i66-west"],
  );
  assert.deepEqual(snapshot.estimates.map(({ outbound, return: returnTrip }) => [
    outbound.origin_point_id,
    outbound.destination_point_id,
    returnTrip.origin_point_id,
    returnTrip.destination_point_id,
  ]), [
    ["i95:218NO", "i95:224ND", "i95:2232SO", "i95:217SD"],
    ["i95:206NO", "i95:224ND", "i95:2232SO", "i95:206SD"],
    ["greenway:1:entry:EB", "i66:16:exit:EB", "i66:16:entry:WB", "greenway:1:exit:WB"],
    ["i66:1:entry:EB", "i66:16:exit:EB", "i66:16:entry:WB", "i66:1:exit:WB"],
  ]);
  for (const estimate of snapshot.estimates) {
    assert.match(formatAnnualToll(estimate.scenarios.p50.annual_toll_usd), /^\$[\d,]+\/yr$/);
    assert.ok(Number(estimate.scenarios.p25.annual_toll_usd) <= Number(estimate.scenarios.p50.annual_toll_usd));
    assert.ok(Number(estimate.scenarios.p50.annual_toll_usd) <= Number(estimate.scenarios.p90.annual_toll_usd));
  }
});

test("estimate validation rejects malformed or unsafe map data", () => {
  assert.throws(() => validateEstimateSnapshot({}), /invalid commute estimate snapshot/);
  assert.throws(
    () => validateEstimateSnapshot({ ...commuteEstimates, estimates: commuteEstimates.estimates.slice(1) }),
    /invalid commute estimate snapshot/,
  );
  assert.throws(
    () => validateEstimateSnapshot({
      ...commuteEstimates,
      estimates: commuteEstimates.estimates.map((estimate, index) => index
        ? estimate
        : { ...estimate, coordinates: ["secret", 38.5] }),
    }),
    /invalid commute estimate snapshot/,
  );
});
