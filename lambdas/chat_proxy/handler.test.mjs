import assert from "node:assert/strict";
import test from "node:test";

import { route } from "./handler.mjs";

const sessionId = "9fd83bc2-6d8b-4d85-b270-f49aa73e41b4";
const sessionToken = "a".repeat(43);
const sessionDependencies = {
  sessionClient: { async send() {
    return { Attributes: { runtime_session_id: { S: sessionId } } };
  } },
  sessionTable: "sessions",
  now: () => 1_700_000_000_000,
  randomBytes: () => Buffer.alloc(32, 7),
  randomUUID: () => sessionId,
};

const event = (method, path, body) => ({
  httpMethod: method,
  path,
  requestContext: { domainName: "preview.tollchat.ai" },
  body: body === undefined ? null : JSON.stringify(body),
  isBase64Encoded: false,
  headers: {
    "content-type": "application/json",
    origin: "https://preview.tollchat.ai",
    "sec-fetch-site": "same-origin",
    cookie: `__Host-tollchat-session=${sessionToken}`,
  },
});

const functionUrlEvent = (method, path, body) => ({
  requestContext: {
    http: { method },
    domainName: "example.lambda-url.us-east-1.on.aws",
  },
  rawPath: path,
  body: body === undefined ? null : JSON.stringify(body),
  isBase64Encoded: false,
  headers: {
    "content-type": "application/json",
    origin: "https://tollchat.ai",
    "sec-fetch-site": "same-origin",
    cookie: `__Host-tollchat-session=${sessionToken}`,
  },
});

const browserEvent = (method, path, body, cookie) => ({
  ...functionUrlEvent(method, path, body),
  headers: {
    "content-type": "application/json",
    origin: "https://tollchat.ai",
    "sec-fetch-site": "same-origin",
    ...(cookie ? { cookie } : {}),
  },
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
      message: "  Price Dumfries to Westpark  ",
    }),
    { ...sessionDependencies, client, runtimeArn: "runtime-arn", previewHtml: "<html></html>" },
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

test("only the trusted private route forwards the runtime failure drill", async () => {
  const calls = [];
  const client = {
    async send(command) {
      calls.push(JSON.parse(new TextDecoder().decode(command.input.payload)));
      return {
        contentType: "text/event-stream",
        response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
      };
    },
  };
  const privateRequest = event("POST", "/api/chat", { message: "verify failure" });
  privateRequest.headers["x-tollchat-drill"] = "runtime-exception-v1";
  const publicRequest = functionUrlEvent("POST", "/api/chat", { message: "ordinary request" });
  publicRequest.headers.origin = "https://preview.tollchat.ai";
  publicRequest.headers["x-tollchat-drill"] = "runtime-exception-v1";

  const dependencies = {
    ...sessionDependencies,
    client,
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };
  const privateResponse = await route(privateRequest, dependencies);
  const publicResponse = await route(publicRequest, dependencies);
  const privateBody = await bodyText(privateResponse.body);
  await bodyText(publicResponse.body);

  assert.deepEqual(calls, [
    { prompt: "verify failure", failure_mode: "runtime_exception_v1" },
    { prompt: "ordinary request" },
  ]);
  assert.doesNotMatch(privateBody, /runtime_exception/);
});

test("chat replaces malformed or internal upstream data with a safe error", async () => {
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => errors.push(args);
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

  let body;
  try {
    const response = await route(
      event("POST", "/api/chat", { message: "hello" }),
      { ...sessionDependencies, client, runtimeArn: "runtime-arn", previewHtml: "" },
    );
    body = await bodyText(response.body);
  } finally {
    console.error = originalError;
  }

  assert.equal(
    body,
    '{"type":"error","code":"agent_unavailable","message":"TollChat is temporarily unavailable. Please try again."}\n',
  );
  assert.doesNotMatch(body, /password|hunter2|raw secret/);
  assert.deepEqual(errors, [["PROXY_FAILURE", "stream", "Error"]]);
});

test("chat requires exactly one terminal upstream event", async () => {
  const terminal = 'data: {"type":"answer","text":"The toll is $4.25.","blocked":false}\n\n';
  const tool = 'data: {"type":"tool","index":0,"label":"Checking I-495 tolls","status":"completed"}\n\n';

  for (const response of [chunks(tool), chunks(terminal, tool)]) {
    const client = { async send() { return { contentType: "text/event-stream", response }; } };
    const result = await route(
      event("POST", "/api/chat", { message: "hello" }),
      { ...sessionDependencies, client, runtimeArn: "runtime-arn", previewHtml: "" },
    );
    const body = await bodyText(result.body);

    assert.match(body, /temporarily unavailable/);
    assert.doesNotMatch(body, /The toll is/);
    assert.equal(body.match(/"type":"(?:answer|error)"/g)?.length, 1);
  }
});

test("chat counts a valid AgentCore dependency error without exposing detail", async () => {
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => errors.push(args);
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks(
        'data: {"type":"error","code":"agent_unavailable","message":"TollChat could not complete that request. Please try again."}\n\n',
      ),
    };
  } };

  let body;
  try {
    const response = await route(
      event("POST", "/api/chat", { message: "hello" }),
      { ...sessionDependencies, client, runtimeArn: "runtime-arn", previewHtml: "" },
    );
    body = await bodyText(response.body);
  } finally {
    console.error = originalError;
  }

  assert.match(body, /could not complete/);
  assert.deepEqual(errors, [["PROXY_FAILURE", "runtime", "agent_unavailable"]]);
});

test("validation, page, config, and reset keep their small contracts", async () => {
  const calls = [];
  const dependencies = {
    ...sessionDependencies,
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
  const privacy = await route(event("GET", "/privacy.txt"), {
    ...dependencies,
    previewAssets: { "/privacy.txt": "# Privacy" },
  });
  assert.equal(privacy.statusCode, 200);
  assert.equal(privacy.headers["Content-Type"], "text/plain; charset=utf-8");
  assert.equal(privacy.headers["Cache-Control"], "no-store");
  assert.equal(await bodyText(privacy.body), "# Privacy");
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
    (await route(event("POST", "/api/reset", {}), dependencies)).statusCode,
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
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => errors.push(args);
  const client = { async send() { throw new Error("credential-shaped detail"); } };
  let response;
  try {
    response = await route(
      event("POST", "/api/chat", { message: "hello" }),
      { ...sessionDependencies, client, runtimeArn: "runtime-arn", previewHtml: "" },
    );
  } finally {
    console.error = originalError;
  }

  assert.equal(response.statusCode, 502);
  const body = await bodyText(response.body);
  assert.match(body, /temporarily unavailable/);
  assert.doesNotMatch(body, /credential-shaped/);
  assert.deepEqual(errors, [["PROXY_FAILURE", "request", "Error"]]);
});

test("reset is idempotent when its runtime session does not exist", async () => {
  const client = { async send() {
    const error = new Error("missing session");
    error.name = "ResourceNotFoundException";
    throw error;
  } };
  const response = await route(
    event("POST", "/api/reset", {}),
    { ...sessionDependencies, client, runtimeArn: "runtime-arn", previewHtml: "" },
  );

  assert.equal(response.statusCode, 200);
  assert.deepEqual(JSON.parse(await bodyText(response.body)), { ok: true });
});

test("Lambda Function URL events keep the existing API contract", async () => {
  const calls = [];
  const dependencies = {
    ...sessionDependencies,
    client: { async send(command) { calls.push(command.input); return {}; } },
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };

  const config = await route(functionUrlEvent("GET", "/api/config"), dependencies);
  assert.equal(config.statusCode, 200);
  assert.deepEqual(JSON.parse(await bodyText(config.body)), {
    chatEnabled: true,
    maxMessageChars: 8000,
    maxTurns: 5,
  });

  const resetEvent = functionUrlEvent("POST", "/api/reset", {});
  resetEvent.cookies = [`__Host-tollchat-session=${sessionToken}`];
  const reset = await route(resetEvent, dependencies);
  assert.equal(reset.statusCode, 200);
  assert.deepEqual(calls, [{
    agentRuntimeArn: "runtime-arn",
    runtimeSessionId: sessionId,
    qualifier: "preview",
  }]);
});

test("first chat creates a backend-owned session and sets a secure cookie", async () => {
  const calls = [];
  const dependencies = {
    client: { async send(command) {
      calls.push([command.constructor.name, command.input]);
      return command.constructor.name === "InvokeAgentRuntimeCommand"
        ? {
            contentType: "text/event-stream",
            response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
          }
        : {};
    } },
    sessionClient: { async send(command) { calls.push([command.constructor.name, command.input]); return {}; } },
    sessionTable: "sessions",
    runtimeArn: "runtime-arn",
    previewHtml: "",
    now: () => 1_700_000_000_000,
    randomBytes: () => Buffer.alloc(32, 7),
    randomUUID: () => sessionId,
  };

  const response = await route(browserEvent("POST", "/api/chat", { message: "hello" }), dependencies);

  assert.equal(response.statusCode, 200);
  assert.match(response.headers["Set-Cookie"], /^__Host-tollchat-session=/);
  for (const attribute of ["Path=/", "Max-Age=3600", "HttpOnly", "Secure", "SameSite=Strict"]) {
    assert.match(response.headers["Set-Cookie"], new RegExp(attribute));
  }
  assert.equal(calls[0][0], "PutItemCommand");
  assert.equal(calls[1][0], "InvokeAgentRuntimeCommand");
  assert.equal(calls[1][1].runtimeSessionId, sessionId);
});

test("browser-selected runtime IDs and cross-site posts are rejected before dependencies", async () => {
  const dependencies = {
    client: { async send() { assert.fail("AgentCore must not be called"); } },
    sessionClient: { async send() { assert.fail("DynamoDB must not be called"); } },
    sessionTable: "sessions",
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };
  const supplied = await route(
    browserEvent("POST", "/api/chat", { session_id: sessionId, message: "hello" }),
    dependencies,
  );
  assert.equal(supplied.statusCode, 400);

  const crossSite = browserEvent("POST", "/api/chat", { message: "hello" });
  crossSite.headers.origin = "https://evil.example";
  crossSite.headers["sec-fetch-site"] = "cross-site";
  assert.equal((await route(crossSite, dependencies)).statusCode, 403);
});

test("unknown, duplicate, and revoked credentials fail alike without invoking AgentCore", async () => {
  const conditional = new Error("not found");
  conditional.name = "ConditionalCheckFailedException";
  const dependencies = {
    ...sessionDependencies,
    client: { async send() { assert.fail("AgentCore must not be called"); } },
    sessionClient: { async send() { throw conditional; } },
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };

  for (const request of [
    browserEvent("POST", "/api/chat", { message: "hello" }, `__Host-tollchat-session=${sessionToken}`),
    browserEvent("POST", "/api/reset", {}, `__Host-tollchat-session=${sessionToken}`),
  ]) {
    const response = await route(request, dependencies);
    assert.equal(response.statusCode, 401);
    assert.equal(JSON.parse(response.body).error.code, "session_expired");
    assert.match(response.headers["Set-Cookie"], /Max-Age=0/);
  }

  const duplicate = browserEvent(
    "POST",
    "/api/chat",
    { message: "hello" },
    `__Host-tollchat-session=${sessionToken}; __Host-tollchat-session=${"b".repeat(43)}`,
  );
  assert.equal((await route(duplicate, dependencies)).statusCode, 401);
});

test("reset revokes before stopping and a stop failure leaves the cookie cleared", async () => {
  const calls = [];
  const dependencies = {
    ...sessionDependencies,
    sessionClient: { async send(command) {
      calls.push(command.constructor.name);
      return { Attributes: { runtime_session_id: { S: sessionId } } };
    } },
    client: { async send(command) {
      calls.push(command.constructor.name);
      throw new Error("upstream failed");
    } },
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };

  const response = await route(browserEvent(
    "POST",
    "/api/reset",
    {},
    `__Host-tollchat-session=${sessionToken}`,
  ), dependencies);

  assert.deepEqual(calls, ["UpdateItemCommand", "StopRuntimeSessionCommand"]);
  assert.equal(response.statusCode, 502);
  assert.match(response.headers["Set-Cookie"], /Max-Age=0/);
});

test("conditional session updates enforce idle, absolute expiry, and revocation", async () => {
  const updates = [];
  const dependencies = {
    ...sessionDependencies,
    sessionClient: { async send(command) {
      updates.push(command.input);
      return { Attributes: { runtime_session_id: { S: sessionId } } };
    } },
    client: { async send() {
      return {
        contentType: "text/event-stream",
        response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
      };
    } },
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };

  const response = await route(browserEvent(
    "POST",
    "/api/chat",
    { message: "hello" },
    `__Host-tollchat-session=${sessionToken}`,
  ), dependencies);
  await bodyText(response.body);

  const update = updates[0];
  assert.match(update.ConditionExpression, /attribute_not_exists\(revoked_at\)/);
  assert.match(update.ConditionExpression, /expires_at > :now/);
  assert.match(update.ConditionExpression, /last_seen_at > :idle_cutoff/);
  assert.match(update.ConditionExpression, /attribute_not_exists\(lease_until\)/);
  assert.match(update.UpdateExpression, /lease_id = :lease_id/);
  assert.equal(update.ExpressionAttributeValues[":idle_cutoff"].N, "1699999100");
  assert.equal(updates[1].UpdateExpression, "REMOVE lease_id, lease_until");
});

test("lease-release failures are counted without replacing a completed answer", async () => {
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => errors.push(args);
  const sessionClient = { async send(command) {
    if (command.input.UpdateExpression === "REMOVE lease_id, lease_until") {
      throw new Error("sensitive detail");
    }
    return { Attributes: { runtime_session_id: { S: sessionId } } };
  } };
  const client = { async send() {
    return {
      contentType: "text/event-stream",
      response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
    };
  } };

  let body;
  try {
    const response = await route(
      event("POST", "/api/chat", { message: "hello" }),
      { ...sessionDependencies, sessionClient, client, runtimeArn: "runtime-arn", previewHtml: "" },
    );
    body = await bodyText(response.body);
  } finally {
    console.error = originalError;
  }

  assert.equal(body, '{"type":"answer","text":"Done","blocked":false}\n');
  assert.deepEqual(errors, [["PROXY_FAILURE", "lease_release", "Error"]]);
});

test("a newly-created credential survives an AgentCore failure for safe retry", async () => {
  const dependencies = {
    ...sessionDependencies,
    sessionClient: { async send() { return {}; } },
    client: { async send() { throw new Error("unavailable"); } },
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };
  const response = await route(browserEvent("POST", "/api/chat", { message: "hello" }), dependencies);

  assert.equal(response.statusCode, 502);
  assert.match(response.headers["Set-Cookie"], /^__Host-tollchat-session=/);
  assert.doesNotMatch(response.body, /unavailable$/);
});

test("reset cannot succeed between chat authorization and invocation", async () => {
  let leaseHeld = false;
  let continueInvoke;
  let invocationStarted;
  const started = new Promise((resolve) => { invocationStarted = resolve; });
  const sessionClient = { async send(command) {
    if (command.input.UpdateExpression?.startsWith("SET last_seen_at")) {
      leaseHeld = true;
      return { Attributes: { runtime_session_id: { S: sessionId } } };
    }
    if (command.input.UpdateExpression === "REMOVE lease_id, lease_until") {
      leaseHeld = false;
      return {};
    }
    if (leaseHeld) {
      const error = new Error("leased");
      error.name = "ConditionalCheckFailedException";
      error.Item = {
        runtime_session_id: { S: sessionId },
        expires_at: { N: "1700003600" },
        last_seen_at: { N: "1700000000" },
        lease_until: { N: "1700000060" },
      };
      throw error;
    }
    return { Attributes: { runtime_session_id: { S: sessionId } } };
  } };
  const client = { async send(command) {
    if (command.constructor.name === "InvokeAgentRuntimeCommand") {
      invocationStarted();
      await new Promise((resolve) => { continueInvoke = resolve; });
      return {
        contentType: "text/event-stream",
        response: chunks('data: {"type":"answer","text":"Done","blocked":false}\n\n'),
      };
    }
    return {};
  } };
  const dependencies = {
    ...sessionDependencies,
    sessionClient,
    client,
    runtimeArn: "runtime-arn",
    previewHtml: "",
  };

  const chat = route(browserEvent(
    "POST",
    "/api/chat",
    { message: "hello" },
    `__Host-tollchat-session=${sessionToken}`,
  ), dependencies);
  await started;
  const racedReset = await route(browserEvent(
    "POST",
    "/api/reset",
    {},
    `__Host-tollchat-session=${sessionToken}`,
  ), dependencies);

  assert.equal(racedReset.statusCode, 409);
  assert.equal(JSON.parse(racedReset.body).error.code, "session_busy");
  continueInvoke();
  const chatResponse = await chat;
  await bodyText(chatResponse.body);
  assert.equal(leaseHeld, false);
  assert.equal((await route(browserEvent(
    "POST",
    "/api/reset",
    {},
    `__Host-tollchat-session=${sessionToken}`,
  ), dependencies)).statusCode, 200);
});
