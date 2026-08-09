import assert from "node:assert/strict";
import test from "node:test";

import { route } from "./handler.mjs";

const sessionId = "9fd83bc2-6d8b-4d85-b270-f49aa73e41b4";

const event = (method, path, body) => ({
  httpMethod: method,
  path,
  body: body === undefined ? null : JSON.stringify(body),
  isBase64Encoded: false,
});

const chunks = async function* (...values) {
  for (const value of values) yield new TextEncoder().encode(value);
};

const bodyText = async (body) => {
  if (typeof body === "string") return body;
  let value = "";
  for await (const chunk of body) value += chunk;
  return value;
};

test("chat forwards validated AgentCore SSE as ordered NDJSON", async () => {
  const calls = [];
  const client = {
    async send(command) {
      calls.push(command.input);
      return {
        contentType: "text/event-stream",
        response: chunks(
          'data: {"type":"tool","index":0,"label":"Checking I-95/395 Express Lanes tolls",',
          '"status":"running"}\n\n',
          'data: {"type":"tool","index":0,"label":"Checking I-95/395 Express Lanes tolls","status":"completed"}\n\n',
          'data: {"type":"answer","text":"The toll is $4.25.","blocked":false}\n\n',
        ),
      };
    },
  };

  const response = await route(
    event("POST", "/api/chat", {
      session_id: sessionId,
      message: "  Price Dumfries to Westpark  ",
    }),
    { client, runtimeArn: "runtime-arn", previewHtml: "<html></html>" },
  );

  assert.equal(response.statusCode, 200);
  assert.equal(response.headers["Content-Type"], "application/x-ndjson");
  assert.deepEqual(calls, [
    {
      agentRuntimeArn: "runtime-arn",
      runtimeSessionId: sessionId,
      qualifier: "preview",
      payload: new TextEncoder().encode(
        JSON.stringify({ prompt: "Price Dumfries to Westpark" }),
      ),
    },
  ]);
  assert.equal(
    await bodyText(response.body),
    [
      '{"type":"tool","index":0,"label":"Checking I-95/395 Express Lanes tolls","status":"running"}',
      '{"type":"tool","index":0,"label":"Checking I-95/395 Express Lanes tolls","status":"completed"}',
      '{"type":"answer","text":"The toll is $4.25.","blocked":false}',
      "",
    ].join("\n"),
  );
});

test("chat replaces malformed or internal upstream data with a safe error", async () => {
  const client = {
    async send() {
      return {
        contentType: "text/event-stream",
        response: chunks(
          'data: {"type":"tool","index":0,"label":"raw secret","status":"running","arguments":{"password":"hunter2"}}\n\n',
        ),
      };
    },
  };

  const response = await route(
    event("POST", "/api/chat", { session_id: sessionId, message: "hello" }),
    { client, runtimeArn: "runtime-arn", previewHtml: "" },
  );
  const body = await bodyText(response.body);

  assert.equal(
    body,
    '{"type":"error","code":"agent_unavailable","message":"TollChat is temporarily unavailable. Please try again."}\n',
  );
  assert.doesNotMatch(body, /password|hunter2|raw secret/);
});

test("chat requires exactly one terminal upstream event", async () => {
  const terminal = 'data: {"type":"answer","text":"The toll is $4.25.","blocked":false}\n\n';
  const tool = 'data: {"type":"tool","index":0,"label":"Checking I-495 tolls","status":"completed"}\n\n';

  for (const response of [chunks(tool), chunks(terminal, tool)]) {
    const client = { async send() { return { contentType: "text/event-stream", response }; } };
    const result = await route(
      event("POST", "/api/chat", { session_id: sessionId, message: "hello" }),
      { client, runtimeArn: "runtime-arn", previewHtml: "" },
    );
    const body = await bodyText(result.body);

    assert.match(body, /temporarily unavailable/);
    assert.doesNotMatch(body, /The toll is/);
    assert.equal(body.match(/"type":"(?:answer|error)"/g)?.length, 1);
  }
});

test("validation, page, config, and reset keep their small contracts", async () => {
  const calls = [];
  const dependencies = {
    client: { async send(command) { calls.push(command.input); return {}; } },
    runtimeArn: "runtime-arn",
    previewHtml: "<!doctype html><title>TollChat preview</title>",
  };

  assert.equal((await route(event("GET", "/"), dependencies)).statusCode, 200);
  assert.equal(
    await bodyText((await route(event("GET", "/"), dependencies)).body),
    dependencies.previewHtml,
  );
  const asset = await route(event("GET", "/assets/chat-markdown-v1.mjs"), {
    ...dependencies,
    previewAssets: { "/assets/chat-markdown-v1.mjs": "export const safe = true;" },
  });
  assert.equal(asset.statusCode, 200);
  assert.equal(asset.headers["Content-Type"], "text/javascript; charset=utf-8");
  assert.equal(asset.headers["Cache-Control"], "public, max-age=31536000, immutable");
  assert.equal(await bodyText(asset.body), "export const safe = true;");
  const coverageMap = await route(event("GET", "/assets/coverage-map-v1.mjs"), {
    ...dependencies,
    previewAssets: { "/assets/coverage-map-v1.mjs": "export const pins = [];" },
  });
  assert.equal(coverageMap.statusCode, 200);
  assert.equal(coverageMap.headers["Cache-Control"], "no-store");
  const stylesheet = await route(event("GET", "/assets/maplibre-gl-6.0.0/maplibre-gl.css"), {
    ...dependencies,
    previewAssets: { "/assets/maplibre-gl-6.0.0/maplibre-gl.css": ".map{}" },
  });
  assert.equal(stylesheet.statusCode, 200);
  assert.equal(stylesheet.headers["Content-Type"], "text/css; charset=utf-8");
  assert.deepEqual(
    JSON.parse(await bodyText((await route(event("GET", "/api/config"), dependencies)).body)),
    { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 },
  );
  assert.equal(
    (await route(event("POST", "/api/chat", { session_id: "bad", message: "hello" }), dependencies)).statusCode,
    400,
  );
  assert.equal(
    (await route(event("POST", "/api/reset", { session_id: sessionId }), dependencies)).statusCode,
    200,
  );
  assert.deepEqual(calls, [
    {
      agentRuntimeArn: "runtime-arn",
      runtimeSessionId: sessionId,
      qualifier: "preview",
    },
  ]);
});

test("AgentCore invocation failures return no internal detail", async () => {
  const client = { async send() { throw new Error("credential-shaped detail"); } };
  const response = await route(
    event("POST", "/api/chat", { session_id: sessionId, message: "hello" }),
    { client, runtimeArn: "runtime-arn", previewHtml: "" },
  );

  assert.equal(response.statusCode, 502);
  const body = await bodyText(response.body);
  assert.match(body, /temporarily unavailable/);
  assert.doesNotMatch(body, /credential-shaped/);
});

test("reset is idempotent when its runtime session does not exist", async () => {
  const client = { async send() {
    const error = new Error("missing session");
    error.name = "ResourceNotFoundException";
    throw error;
  } };
  const response = await route(
    event("POST", "/api/reset", { session_id: sessionId }),
    { client, runtimeArn: "runtime-arn", previewHtml: "" },
  );

  assert.equal(response.statusCode, 200);
  assert.deepEqual(JSON.parse(await bodyText(response.body)), { ok: true });
});
