import assert from "node:assert/strict";
import test from "node:test";

import { route } from "./handler.mjs";

const domain = "abc-vpce.execute-api.us-east-1.amazonaws.com";
const sessionId = "9fd83bc2-6d8b-4d85-b270-f49aa73e41b4";
const token = "a".repeat(43);
const event = (path, body, origin = `https://${domain}`) => ({
  httpMethod: "POST",
  path,
  requestContext: { domainName: domain },
  body: JSON.stringify(body),
  isBase64Encoded: false,
  headers: {
    "content-type": "application/json",
    origin,
    "sec-fetch-site": "same-origin",
    cookie: `__Host-tollchat-session=${token}`,
  },
});
const dependencies = (client) => ({
  client,
  sessionClient: { async send() {
    return { Attributes: { runtime_session_id: { S: sessionId } } };
  } },
  sessionTable: "sessions",
  now: () => 1_700_000_000_000,
  randomBytes: () => Buffer.alloc(32, 7),
  randomUUID: () => sessionId,
  runtimeArn: "runtime-arn",
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

test("private same-origin chat streams only approved v2 events", async () => {
  const calls = [];
  const client = { async send(command) {
    calls.push(command.input);
    return {
      contentType: "text/event-stream",
      response: chunks(
        'data: {"type":"tool","index":0,"label":"Checking current toll price","status":"running"}\n\n',
        'data: {"type":"answer","text":"$4.25","blocked":false}\n\n',
      ),
    };
  } };
  const response = await route(event("/api/chat", { message: " Price it " }), dependencies(client));
  assert.equal(response.statusCode, 200);
  assert.equal(await bodyText(response.body), [
    '{"type":"tool","index":0,"label":"Checking current toll price","status":"running"}',
    '{"type":"answer","text":"$4.25","blocked":false}',
    "",
  ].join("\n"));
  assert.equal(new TextDecoder().decode(calls[0].payload), '{"prompt":"Price it"}');
});

test("public CloudFront origin can invoke the Function URL", async () => {
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"$4.25","blocked":false}\n\n'),
    };
  } };

  for (const origin of ["https://tollchat.ai", "https://www.tollchat.ai"]) {
    const publicEvent = event("/api/chat", { message: "Price it" }, origin);
    publicEvent.requestContext.domainName = "abc.lambda-url.us-east-1.on.aws";
    const response = await route(publicEvent, dependencies(client));
    assert.equal(response.statusCode, 200);
  }
});

test("proxy rejects cross-origin and malformed upstream data", async () => {
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"tool","index":0,"label":"secret","status":"running"}\n\n'),
    };
  } };
  assert.equal(
    (await route(event("/api/chat", { message: "Price it" }, "https://evil.example"), dependencies(client))).statusCode,
    403,
  );
  const response = await route(event("/api/chat", { message: "Price it" }), dependencies(client));
  assert.equal(
    await bodyText(response.body),
    '{"type":"error","code":"agent_unavailable","message":"TollChat is temporarily unavailable. Please try again."}\n',
  );
});

test("config is available without a frontend", async () => {
  const response = await route(
    { httpMethod: "GET", path: "/api/config", requestContext: { domainName: domain }, headers: {} },
    dependencies({}),
  );
  assert.deepEqual(JSON.parse(response.body), { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 });
});
