import assert from "node:assert/strict";
import test from "node:test";

import { consumeNdjson, validStreamEvent } from "../agent/dev_chat.mjs";
import { renderAssistantMarkdown } from "../agent/assets/chat-markdown.mjs";

const stream = (...chunks) => new ReadableStream({
  start(controller) {
    for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
    controller.close();
  },
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
