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

test("public first chat atomically counts one included session and completed answer", async () => {
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

  assert.deepEqual(writes.map(({ name }) => name), [
    "TransactWriteItemsCommand",
    "TransactWriteItemsCommand",
    "UpdateItemCommand",
  ]);
  const [engagement, completion] = writes;
  assert.equal(
    engagement.input.TransactItems[0].Put.Item.usage_excluded.BOOL,
    false,
  );
  assert.equal(
    engagement.input.TransactItems[1].Update.ExpressionAttributeNames["#metric"],
    "engaged_sessions",
  );
  assert.equal(
    completion.input.TransactItems[1].Update.ExpressionAttributeNames["#metric"],
    "completed_responses",
  );
  assert.match(
    completion.input.TransactItems[0].Update.ConditionExpression,
    /usage_excluded.*lease_id.*counted_response_ids/,
  );
  assert.notEqual(engagement.input.ClientRequestToken, completion.input.ClientRequestToken);
});

test("browser opt-out persists on a new session and suppresses both counters", async () => {
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
  assert.equal(writes[0].input.Item.usage_excluded.BOOL, true);
  assert.equal(writes.some(({ name }) => name === "TransactWriteItemsCommand"), false);
});

test("persisted and legacy exclusion state wins over the current cookie", async () => {
  for (const [usageExcluded, currentCookies, expectedTransactions] of [
    [true, [], 0],
    [undefined, [], 0],
    [false, ["tollchat_usage_optout=1"], 1],
  ]) {
    const writes = [];
    const sessionClient = { async send(command) {
      writes.push({ name: command.constructor.name, input: command.input });
      if (command.constructor.name === "UpdateItemCommand" && command.input.ReturnValues === "ALL_NEW") {
        return {
          Attributes: {
            runtime_session_id: { S: sessionId },
            ...(usageExcluded === undefined ? {} : { usage_excluded: { BOOL: usageExcluded } }),
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
    const request = publicEvent(
      { message: "Again" },
      [`__Host-tollchat-session=${token}`, ...currentCookies],
    );

    const response = await route(request, dependencies(client, sessionClient));
    await bodyText(response.body);

    assert.equal(
      writes.filter(({ name }) => name === "TransactWriteItemsCommand").length,
      expectedTransactions,
    );
  }
});

test("a malformed trailing frame does not count the preceding answer", async () => {
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
  assert.equal(
    writes.filter(({ name }) => name === "TransactWriteItemsCommand").length,
    1,
  );
});

test("private preview never writes aggregate transactions", async () => {
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
  assert.equal(writes[0].input.Item.usage_excluded.BOOL, true);
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

test("config is available without a frontend", async () => {
  const response = await route(
    { httpMethod: "GET", path: "/api/config", requestContext: { domainName: domain }, headers: {} },
    dependencies({}),
  );
  assert.deepEqual(JSON.parse(response.body), { chatEnabled: true, maxMessageChars: 8000, maxTurns: 5 });
});
