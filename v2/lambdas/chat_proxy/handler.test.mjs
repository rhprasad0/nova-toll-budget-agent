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
const publicEvent = (body, cookies = []) => ({
  version: "2.0",
  rawPath: "/api/chat",
  requestContext: {
    domainName: "abc.lambda-url.us-east-1.on.aws",
    http: { method: "POST" },
  },
  body: JSON.stringify(body),
  isBase64Encoded: false,
  cookies,
  headers: {
    "content-type": "application/json",
    origin: "https://tollchat.ai",
    "sec-fetch-site": "same-origin",
  },
});
const dependencies = (client, sessionClient = { async send() {
  return { Attributes: { runtime_session_id: { S: sessionId } } };
} }) => ({
  client,
  sessionClient,
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

test("the exact marker carries one bounded canary event and rejects it otherwise", async () => {
  const prompt = "What is the current toll from the Leesburg Bypass entrance to Route 28 for a two-axle vehicle with E-ZPass?";
  const canary = '{"type":"canary","schema_version":1,"call_count":1,"tool_name_match":true,"route_profile_match":true,"correlation_match":true,"result_success":true,"total_usd":"4.25","success":true}';
  const calls = [];
  const client = { async send(command) {
    calls.push(command.input);
    return { contentType: "text/event-stream", response: chunks(`data: ${canary}\n\n`, 'data: {"type":"answer","text":"$4.25","blocked":false}\n\n') };
  } };
  const request = event("/api/chat", { message: prompt });
  request.headers["x-tollchat-canary"] = "greenway-canary-v1";
  const response = await route(request, dependencies(client));
  assert.match(await bodyText(response.body), /"type":"canary"/);
  assert.equal(new TextDecoder().decode(calls[0].payload), JSON.stringify({ prompt, canary_marker: "greenway-canary-v1" }));

  const unmarked = await route(event("/api/chat", { message: prompt }), dependencies(client));
  assert.equal(await bodyText(unmarked.body), '{"type":"error","code":"agent_unavailable","message":"TollChat is temporarily unavailable. Please try again."}\n');
});

test("public CloudFront origin can invoke the Function URL", async () => {
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"$4.25","blocked":false}\n\n'),
    };
  } };

  for (const origin of ["https://tollchat.ai", "https://www.tollchat.ai"]) {
    const request = publicEvent({ message: "Price it" });
    request.headers.origin = origin;
    const response = await route(request, dependencies(client));
    assert.equal(response.statusCode, 200);
    await bodyText(response.body);
  }
});

test("public first chat creates a leased session without usage fields", async () => {
  const writes = [];
  const sessionClient = { async send(command) {
    writes.push({ name: command.constructor.name, input: command.input });
    return {};
  } };
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"$4.25","blocked":true}\n\n'),
    };
  } };

  const response = await route(publicEvent({ message: "Price it" }), dependencies(client, sessionClient));
  assert.equal(response.statusCode, 200);
  await bodyText(response.body);

  assert.deepEqual(writes.map(({ name }) => name), ["PutItemCommand", "UpdateItemCommand"]);
  assert.equal("usage_excluded" in writes[0].input.Item, false);
  assert.equal("counted_response_ids" in writes[0].input.Item, false);
  assert.doesNotMatch(JSON.stringify(writes[0].input), /usage#all/);
});

test("browser usage cookies do not change the session write", async () => {
  const writes = [];
  const sessionClient = { async send(command) {
    writes.push({ name: command.constructor.name, input: command.input });
    return {};
  } };
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"No charge","blocked":true}\n\n'),
    };
  } };
  const request = publicEvent(
    { message: "Price it" },
    ["tollchat_usage_optout=0", "noise=x; tollchat_usage_optout=1"],
  );

  const response = await route(request, dependencies(client, sessionClient));
  await bodyText(response.body);

  assert.deepEqual(writes.map(({ name }) => name), ["PutItemCommand", "UpdateItemCommand"]);
  assert.equal("usage_excluded" in writes[0].input.Item, false);
  assert.equal("counted_response_ids" in writes[0].input.Item, false);
  assert.equal(writes.some(({ name }) => name === "TransactWriteItemsCommand"), false);
});

test("legacy usage fields do not block a hashed session lease or release", async () => {
  const writes = [];
  const sessionClient = { async send(command) {
    writes.push({ name: command.constructor.name, input: command.input });
    if (command.constructor.name === "UpdateItemCommand" && command.input.ReturnValues === "ALL_NEW") {
      return {
        Attributes: {
          credential_hash: { S: "ignored" },
          runtime_session_id: { S: sessionId },
          usage_excluded: { BOOL: false },
          counted_response_ids: { SS: ["old-request"] },
        },
      };
    }
    return {};
  } };
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
    };
  } };
  const response = await route(
    publicEvent({ message: "Again" }, [`__Host-tollchat-session=${token}`]),
    dependencies(client, sessionClient),
  );
  await bodyText(response.body);

  assert.deepEqual(writes.map(({ name }) => name), ["UpdateItemCommand", "UpdateItemCommand"]);
  assert.equal(
    writes[0].input.Key.credential_hash.S,
    "66d34fba71f8f450f7e45598853e53bfc23bbd129027cbb131a2f4ffd7878cd0",
  );
  assert.match(writes[0].input.UpdateExpression, /lease_id/);
  assert.match(writes[1].input.UpdateExpression, /REMOVE lease_id/);
});

test("a malformed trailing frame becomes a safe stream error and releases its lease", async () => {
  const writes = [];
  const sessionClient = { async send(command) {
    writes.push({ name: command.constructor.name, input: command.input });
    return {};
  } };
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks(
        'data: {"type":"answer","text":"Done","blocked":false}\n\n',
        "not-an-sse-frame\n\n",
      ),
    };
  } };

  const response = await route(publicEvent({ message: "Price it" }), dependencies(client, sessionClient));
  const output = await bodyText(response.body);

  assert.match(output, /agent_unavailable/);
  const leaseWrites = writes.filter(({ name }) => name === "UpdateItemCommand");
  assert.equal(leaseWrites.length, 1);
  assert.equal(leaseWrites[0].input.UpdateExpression, "REMOVE lease_id, lease_until");
  assert.equal(
    leaseWrites[0].input.ExpressionAttributeValues[":lease_id"].S,
    writes[0].input.Item.lease_id.S,
  );
  assert.equal(writes.some(({ name }) => name === "TransactWriteItemsCommand"), false);
});

test("session state rejection never invokes the runtime", async () => {
  const cases = [
    {
      name: "busy session",
      expectedStatus: 409,
      item: {
        runtime_session_id: { S: sessionId },
        expires_at: { N: "1700003600" },
        last_seen_at: { N: "1700000000" },
        lease_until: { N: "1700000010" },
      },
    },
    {
      name: "expired session",
      expectedStatus: 401,
      item: {
        runtime_session_id: { S: sessionId },
        expires_at: { N: "1699999999" },
        last_seen_at: { N: "1700000000" },
      },
    },
  ];

  for (const sessionCase of cases) {
    const sessionCalls = [];
    let runtimeCalls = 0;
    const sessionClient = { async send(command) {
      sessionCalls.push(command.input);
      const error = new Error("conditional failure");
      error.name = "ConditionalCheckFailedException";
      error.Item = sessionCase.item;
      throw error;
    } };
    const client = { async send() {
      runtimeCalls += 1;
      throw new Error(`${sessionCase.name} invoked runtime`);
    } };

    const response = await route(
      publicEvent({ message: "Price it" }, [`__Host-tollchat-session=${token}`]),
      dependencies(client, sessionClient),
    );

    assert.equal(response.statusCode, sessionCase.expectedStatus, sessionCase.name);
    assert.equal(runtimeCalls, 0, sessionCase.name);
    assert.equal(sessionCalls.length, 1, sessionCase.name);
  }
});

test("invalid cookies reject before session or runtime access", async () => {
  let sessionCalls = 0;
  let runtimeCalls = 0;
  const sessionClient = { async send() {
    sessionCalls += 1;
    throw new Error("invalid cookie accessed session");
  } };
  const client = { async send() {
    runtimeCalls += 1;
    throw new Error("invalid cookie invoked runtime");
  } };

  const response = await route(
    publicEvent({ message: "Price it" }, ["__Host-tollchat-session=not-a-token"]),
    dependencies(client, sessionClient),
  );

  assert.equal(response.statusCode, 401);
  assert.equal(sessionCalls, 0);
  assert.equal(runtimeCalls, 0);
});

test("reset revokes the session and stops its runtime", async () => {
  const sessionCalls = [];
  const runtimeCalls = [];
  const sessionClient = { async send(command) {
    sessionCalls.push(command);
    return {
      Attributes: { runtime_session_id: { S: sessionId } },
    };
  } };
  const client = { async send(command) {
    runtimeCalls.push(command);
    return {};
  } };

  const response = await route(
    { ...publicEvent({}, [`__Host-tollchat-session=${token}`]), rawPath: "/api/reset" },
    dependencies(client, sessionClient),
  );

  assert.equal(response.statusCode, 200);
  assert.match(response.headers["Set-Cookie"], /Max-Age=0/);
  assert.equal(sessionCalls.length, 1);
  assert.equal(sessionCalls[0].input.UpdateExpression, "SET revoked_at = :now");
  assert.equal(runtimeCalls.length, 1);
  assert.equal(runtimeCalls[0].input.runtimeSessionId, sessionId);
});

test("an upstream invocation error releases the matching lease", async () => {
  const writes = [];
  const sessionClient = { async send(command) {
    writes.push({ name: command.constructor.name, input: command.input });
    return {};
  } };
  const client = { async send() {
    throw new Error("runtime unavailable");
  } };

  const response = await route(publicEvent({ message: "Price it" }), dependencies(client, sessionClient));

  assert.equal(response.statusCode, 502);
  const release = writes.find(({ input }) => input.UpdateExpression === "REMOVE lease_id, lease_until");
  assert.ok(release);
  assert.equal(release.input.ExpressionAttributeValues[":lease_id"].S, writes[0].input.Item.lease_id.S);
});

test("private preview still uses the normal session write", async () => {
  const writes = [];
  const sessionClient = { async send(command) {
    writes.push({ name: command.constructor.name, input: command.input });
    return {};
  } };
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
    };
  } };
  const request = event("/api/chat", { message: "Price it" });
  delete request.headers.cookie;

  const response = await route(request, dependencies(client, sessionClient));
  await bodyText(response.body);

  assert.equal(writes[0].name, "PutItemCommand");
  assert.equal("usage_excluded" in writes[0].input.Item, false);
  assert.equal(writes.some(({ name }) => name === "TransactWriteItemsCommand"), false);
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

test("proxy accepts only the configured development origin", async () => {
  const previous = process.env.PUBLIC_ORIGINS;
  process.env.PUBLIC_ORIGINS = "https://dev.tollchat.ai";
  try {
    const fresh = await import(`./handler.mjs?development-origin=${Date.now()}`);
    const client = { async send() {
      return { contentType: "text/event-stream", response: chunks('data: {"type":"final","text":"ok"}\n\n') };
    } };
    const request = publicEvent({ message: "Price it" });
    request.headers.origin = "https://dev.tollchat.ai";
    assert.notEqual((await fresh.route(request, dependencies(client))).statusCode, 403);
    request.headers.origin = "https://evil.example";
    assert.equal((await fresh.route(request, dependencies(client))).statusCode, 403);
  } finally {
    if (previous === undefined) delete process.env.PUBLIC_ORIGINS;
    else process.env.PUBLIC_ORIGINS = previous;
  }
});

test("config is available without a frontend", async () => {
  const response = await route(
    { httpMethod: "GET", path: "/api/config", requestContext: { domainName: domain }, headers: {} },
    dependencies({}),
  );
  assert.deepEqual(JSON.parse(response.body), { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 });
});
