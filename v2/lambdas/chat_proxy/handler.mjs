/** @typedef {{httpMethod?: string, path?: string, rawPath?: string, version?: string, requestContext?: {domainName?: string, http?: {method?: string}}, body?: string, isBase64Encoded?: boolean, headers?: Record<string, string>, cookies?: string[]}} RequestEvent */
/** @typedef {import("@aws-sdk/client-bedrock-agentcore").InvokeAgentRuntimeCommand | import("@aws-sdk/client-bedrock-agentcore").StopRuntimeSessionCommand} RuntimeCommand */
/** @typedef {{send(command: RuntimeCommand): Promise<{contentType?: string, response?: unknown, $metadata?: object}>}} RuntimeClient */
/** @typedef {import("@aws-sdk/client-dynamodb").PutItemCommand | import("@aws-sdk/client-dynamodb").UpdateItemCommand} SessionCommand */
/** @typedef {{send(command: SessionCommand): Promise<{Attributes?: Record<string, import("@aws-sdk/client-dynamodb").AttributeValue>}>}} SessionClient */
/** @typedef {{client: RuntimeClient, sessionClient: SessionClient, sessionTable?: string, now(): number, randomBytes(size: number): Buffer, randomUUID(): string, runtimeArn?: string, runtimeEndpoint?: string, releaseId?: string, proxyArn?: string, proxyVersion?: string, runtimeVersion?: string}} Dependencies */
/** @typedef {{statusCode: number, headers: Record<string, string>, body: string | AsyncIterable<string>}} Response */
/** @typedef {import("../../agent/public_chat.mjs").PublicEvent | {type: "canary", schema_version: number, call_count: number, tool_name_match: boolean, route_profile_match: boolean, correlation_match: boolean, result_success: boolean, total_usd: string | null, success: boolean, release_id?: string}} StreamEvent */
import { createHash, randomBytes, randomUUID } from "node:crypto";
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
  StopRuntimeSessionCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import {
  DynamoDBClient,
  PutItemCommand,
  UpdateItemCommand,
} from "@aws-sdk/client-dynamodb";

const MAX_MESSAGE_CHARS = 8_000;
const IDLE_SECONDS = 15 * 60;
const MAX_SESSION_SECONDS = 60 * 60;
const LEASE_SECONDS = 60;
const COOKIE = "__Host-tollchat-session";
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const PUBLIC_ORIGINS = new Set((process.env.PUBLIC_ORIGINS ?? "https://tollchat.ai,https://www.tollchat.ai")
  .split(",").filter(Boolean));
const DRILL_MODE = "runtime_exception_v2";
const CANARY_MARKER = "greenway-canary-v1";
const CANARY_PROMPT = "What is the current toll from the Leesburg Bypass entrance to Route 28 for a two-axle vehicle with E-ZPass?";
const SAFE_ERROR = {
  type: "error",
  code: "agent_unavailable",
  message: "TollChat is temporarily unavailable. Please try again.",
};
const LABELS = new Set([
  "Checking current toll price",
  "Calculating annual toll-commute affordability",
  "Checking toll data",
]);
const STATUS = new Set(["running", "completed", "failed"]);
const ERROR_CODES = new Set(["invalid_request", "turn_limit", "agent_unavailable"]);
const ERROR_MESSAGES = new Set([
  "Provide a message between 1 and 8000 characters.",
  "Start a new chat to continue.",
  "TollChat could not complete that request. Please try again.",
]);

/** @param {number} statusCode @param {unknown} value @param {Record<string, string>} headers @returns {Response} */
const json = (statusCode, value, headers = {}) => ({
  statusCode,
  headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers },
  body: JSON.stringify(value),
});

const invalid = () => json(400, {
  error: { code: "invalid_request", message: "Provide a valid message." },
});

const forbidden = () => json(403, {
  error: { code: "forbidden", message: "Request not allowed." },
});

const clearCookie = `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
const expired = (updated = false) => json(401, {
  error: { code: "session_expired", message: updated ? "The application was updated. Start a new conversation." : "Your chat expired. Please send your question again." },
}, { "Set-Cookie": clearCookie });
const busy = () => json(409, {
  error: { code: "session_busy", message: "Wait for the current response to finish." },
});

/** @param {RequestEvent} event @returns {Record<string, unknown> | null} */
const parseBody = (event) => {
  if (typeof event.body !== "string" || event.body.length > MAX_MESSAGE_CHARS + 512) return null;
  try {
    const raw = event.isBase64Encoded
      ? Buffer.from(event.body, "base64").toString("utf8")
      : event.body;
    const value = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
};

/** @param {object} value @param {string[]} keys */
const exactKeys = (value, keys) =>
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");

/** @param {RequestEvent} event @param {string} name */
const header = (event, name) => Object.entries(event.headers ?? {})
  .find(([key]) => key.toLowerCase() === name)?.[1];

/** @param {RequestEvent} event */
const validPost = (event) => {
  const contentType = header(event, "content-type")?.split(";", 1)[0].trim().toLowerCase();
  try {
    const origin = new URL(/** @type {string} */ (header(event, "origin")));
    return contentType === "application/json"
      && origin.protocol === "https:"
      && (origin.host === event.requestContext?.domainName || PUBLIC_ORIGINS.has(origin.origin))
      && origin.pathname === "/"
      && !origin.search && !origin.hash && !origin.username && !origin.password
      && header(event, "sec-fetch-site") === "same-origin";
  } catch {
    return false;
  }
};

/** @param {RequestEvent} event @param {string} wanted */
const cookieValues = (event, wanted) => {
  const values = [];
  const sources = event.cookies?.length ? event.cookies : [header(event, "cookie") ?? ""];
  for (const source of sources.filter(Boolean)) {
    for (const part of source.split(";")) {
      const [name, ...raw] = part.trim().split("=");
      if (name === wanted) values.push(raw.join("="));
    }
  }
  return values;
};

/** @param {RequestEvent} event @returns {{kind: "missing"} | {kind: "invalid"} | {kind: "valid", token: string}} */
const credential = (event) => {
  const values = cookieValues(event, COOKIE);
  if (!values.length) return { kind: "missing" };
  if (values.length !== 1 || !TOKEN.test(values[0])) return { kind: "invalid" };
  return { kind: "valid", token: values[0] };
};

/** @param {string} token */
const tokenHash = (token) => createHash("sha256").update(token).digest("hex");
/** @param {string} token */
const sessionCookie = (token) =>
  `${COOKIE}=${token}; Path=/; Max-Age=${MAX_SESSION_SECONDS}; HttpOnly; Secure; SameSite=Strict`;

/** @param {unknown} error @returns {error is import("@aws-sdk/client-dynamodb").ConditionalCheckFailedException} */
const conditionalFailure = (error) => /** @type {Error | null} */ (error)?.name === "ConditionalCheckFailedException";

/** @param {Dependencies} dependencies @param {string} leaseId */
const createSession = async (dependencies, leaseId) => {
  const now = Math.floor(dependencies.now() / 1000);
  const token = dependencies.randomBytes(32).toString("base64url");
  const runtimeSessionId = dependencies.randomUUID();
  const put = {
    TableName: dependencies.sessionTable,
    Item: {
      credential_hash: { S: tokenHash(token) },
      runtime_session_id: { S: runtimeSessionId },
      release_id: { S: /** @type {string} */ (dependencies.releaseId) },
      created_at: { N: String(now) },
      last_seen_at: { N: String(now) },
      expires_at: { N: String(now + MAX_SESSION_SECONDS) },
      lease_id: { S: leaseId },
      lease_until: { N: String(now + LEASE_SECONDS) },
    },
    ConditionExpression: "attribute_not_exists(credential_hash)",
  };
  await dependencies.sessionClient.send(new PutItemCommand(put));
  return { runtimeSessionId, token, cookie: sessionCookie(token) };
};

/** @param {Dependencies} dependencies @param {string} token @param {string} update @param {string} [leaseId] @returns {Promise<{kind: "ok", runtimeSessionId: string} | {kind: "updated"} | {kind: "busy"} | {kind: "expired"}>} */
const updateSession = async (dependencies, token, update, leaseId) => {
  const now = Math.floor(dependencies.now() / 1000);
  const acquiring = update === "last_seen_at";
  try {
    const result = await dependencies.sessionClient.send(new UpdateItemCommand({
      TableName: dependencies.sessionTable,
      Key: { credential_hash: { S: tokenHash(token) } },
      UpdateExpression: acquiring
        ? "SET last_seen_at = :now, lease_id = :lease_id, lease_until = :lease_until"
        : "SET revoked_at = :now",
      ConditionExpression: [
        "attribute_exists(credential_hash)",
        "attribute_not_exists(revoked_at)",
        "release_id = :release_id",
        "expires_at > :now",
        "last_seen_at > :idle_cutoff",
        "(attribute_not_exists(lease_until) OR lease_until <= :now)",
      ].join(" AND "),
      ExpressionAttributeValues: {
        ":now": { N: String(now) },
        ":idle_cutoff": { N: String(now - IDLE_SECONDS) },
        ":release_id": { S: /** @type {string} */ (dependencies.releaseId) },
        ...(acquiring ? {
          ":lease_id": { S: /** @type {string} */ (leaseId) },
          ":lease_until": { N: String(now + LEASE_SECONDS) },
        } : {}),
      },
      ReturnValues: "ALL_NEW",
      ReturnValuesOnConditionCheckFailure: "ALL_OLD",
    }));
    const runtimeSessionId = result.Attributes?.runtime_session_id?.S;
    if (!runtimeSessionId) throw new Error("session record missing runtime id");
    return { kind: "ok", runtimeSessionId };
  } catch (error) {
    if (conditionalFailure(error)) {
      const item = error.Item;
      if (item && item.release_id?.S !== dependencies.releaseId) return { kind: "updated" };
      const activeLease = Number(item?.lease_until?.N) > now;
      const current = Number(item?.expires_at?.N) > now
        && Number(item?.last_seen_at?.N) > now - IDLE_SECONDS
        && !item?.revoked_at;
      return { kind: current && activeLease ? "busy" : "expired" };
    }
    throw error;
  }
};

/** @param {Dependencies} dependencies @param {string} token @param {string} leaseId */
const releaseSession = async (dependencies, token, leaseId) => {
  try {
    await dependencies.sessionClient.send(new UpdateItemCommand({
      TableName: dependencies.sessionTable,
      Key: { credential_hash: { S: tokenHash(token) } },
      UpdateExpression: "REMOVE lease_id, lease_until",
      ConditionExpression: "lease_id = :lease_id",
      ExpressionAttributeValues: { ":lease_id": { S: leaseId } },
    }));
  } catch (error) {
    if (!conditionalFailure(error)) console.error("PROXY_FAILURE", "lease_release", /** @type {Error | null} */ (error)?.name ?? "Error");
  }
};

/** @param {unknown} input @param {boolean} allowCanary @returns {input is StreamEvent} */
const validEvent = (input, allowCanary = false) => {
  const value = /** @type {StreamEvent} */ (input);
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (value.type === "tool") {
    return exactKeys(value, ["type", "index", "label", "status"])
      && Number.isInteger(value.index) && value.index >= 0
      && LABELS.has(value.label) && STATUS.has(value.status);
  }
  if (value.type === "answer") {
    return exactKeys(value, ["type", "text", "blocked"])
      && typeof value.text === "string" && typeof value.blocked === "boolean";
  }
  if (value.type === "canary") {
    return allowCanary
      && exactKeys(value, ["type", "schema_version", "call_count", "tool_name_match", "route_profile_match", "correlation_match", "result_success", "total_usd", "success", ...(value.release_id !== undefined ? ["release_id"] : [])])
      && (value.release_id === undefined || (typeof value.release_id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.release_id)))
      && value.schema_version === 1 && Number.isInteger(value.call_count) && value.call_count >= 0
      && ["tool_name_match", "route_profile_match", "correlation_match", "result_success", "success"].every((key) => typeof value[/** @type {keyof typeof value} */ (key)] === "boolean")
      && (value.total_usd === null || (typeof value.total_usd === "string" && /^\d{1,4}\.\d{2}$/.test(value.total_usd)));
  }
  return value.type === "error"
    && exactKeys(value, ["type", "code", "message"])
    && ERROR_CODES.has(value.code) && ERROR_MESSAGES.has(value.message);
};

/** @param {AsyncIterable<Uint8Array>} stream @param {() => Promise<void>} release @param {boolean} allowCanary */
async function* ndjsonFromSse(
  stream,
  release = async () => {},
  allowCanary = false,
) {
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal;
  try {
    for await (const chunk of stream) {
      buffer += decoder.decode(chunk, { stream: true }).replaceAll("\r", "");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (!frame || frame.startsWith(":")) continue;
        const lines = frame.split("\n");
        if (lines.some((line) => !line.startsWith("data: "))) throw new Error("invalid SSE frame");
        /** @type {unknown} */
      const value = JSON.parse(lines.map((line) => line.slice(6)).join("\n"));
        if (!validEvent(value, allowCanary)) throw new Error("invalid stream event");
        if (terminal) throw new Error("event after terminal");
        if (value.type === "answer" || value.type === "error") terminal = value;
        else yield `${JSON.stringify(value)}\n`;
      }
    }
    if (buffer.trim()) throw new Error("incomplete SSE frame");
    if (!terminal) throw new Error("missing terminal event");
    if (terminal.type === "error" && terminal.code === "agent_unavailable") {
      console.error("PROXY_FAILURE", "runtime", terminal.code);
    }
    yield `${JSON.stringify(terminal)}\n`;
  } catch (error) {
    console.error("PROXY_FAILURE", "stream", /** @type {Error | null} */ (error)?.name ?? "Error");
    yield `${JSON.stringify(SAFE_ERROR)}\n`;
  } finally {
    await release();
  }
}

/** @param {RequestEvent} event @param {Dependencies} dependencies @returns {Promise<Response>} */
export async function route(event, dependencies) {
  const { client, runtimeArn, runtimeEndpoint, releaseId } = dependencies;
  if (!releaseId || !runtimeEndpoint || runtimeEndpoint === "DEFAULT") {
    return json(503, { error: SAFE_ERROR });
  }
  const method = event.httpMethod ?? event.requestContext?.http?.method;
  const path = event.path ?? event.rawPath;
  if (method === "GET" && path === "/api/config") {
    return json(200, { chatEnabled: true, maxMessageChars: MAX_MESSAGE_CHARS, maxTurns: 5, release_id: releaseId });
  }
  if (method !== "POST" || !["/api/chat", "/api/reset"].includes(/** @type {string} */ (path))) {
    return json(404, { error: { code: "not_found" } });
  }
  if (!validPost(event)) return forbidden();
  const body = parseBody(event);
  if (!body || (path === "/api/chat" ? !exactKeys(body, ["message"]) : !exactKeys(body, []))) return invalid();
  const supplied = credential(event);
  if (supplied.kind === "invalid") return expired();
  let cookie;
  let release = async () => {};
  try {
    if (path === "/api/reset") {
      if (supplied.kind === "missing") return json(200, { ok: true }, { "Set-Cookie": clearCookie });
      const session = await updateSession(dependencies, supplied.token, "revoked_at");
      if (session.kind === "busy") return busy();
      if (session.kind === "expired" || session.kind === "updated") return expired(session.kind === "updated");
      cookie = clearCookie;
      await client.send(new StopRuntimeSessionCommand({
        agentRuntimeArn: runtimeArn,
        runtimeSessionId: session.runtimeSessionId,
        qualifier: runtimeEndpoint,
      }));
      return json(200, { ok: true }, { "Set-Cookie": cookie });
    }
    if (typeof body.message !== "string" || !body.message.trim() || body.message.trim().length > MAX_MESSAGE_CHARS) return invalid();
    let runtimeSessionId;
    const leaseId = dependencies.randomUUID();
    let sessionToken;
    if (supplied.kind === "missing") {
      const created = await createSession(dependencies, leaseId);
      runtimeSessionId = created.runtimeSessionId;
      sessionToken = created.token;
      cookie = created.cookie;
    } else {
      const session = await updateSession(dependencies, supplied.token, "last_seen_at", leaseId);
      if (session.kind === "busy") return busy();
      if (session.kind === "expired" || session.kind === "updated") return expired(session.kind === "updated");
      runtimeSessionId = session.runtimeSessionId;
      sessionToken = supplied.token;
    }
    let leaseHeld = true;
    release = async () => {
      if (!leaseHeld) return;
      leaseHeld = false;
      await releaseSession(dependencies, sessionToken, leaseId);
    };
    const canary = header(event, "x-tollchat-canary") === CANARY_MARKER
      && body.message.trim() === CANARY_PROMPT;
    const result = await client.send(new InvokeAgentRuntimeCommand({
      agentRuntimeArn: runtimeArn,
      runtimeSessionId,
      qualifier: runtimeEndpoint,
      payload: new TextEncoder().encode(JSON.stringify({
        prompt: body.message.trim(),
          ...(validPost(event)
          && header(event, "x-tollchat-drill") === "runtime-exception-v2"
          ? { failure_mode: DRILL_MODE }
          : {}),
        ...(canary ? { canary_marker: CANARY_MARKER } : {}),
      })),
    }));
    if (!result.contentType?.includes("text/event-stream") || !/** @type {AsyncIterable<Uint8Array> | undefined} */ (result.response)?.[Symbol.asyncIterator]) throw new Error("invalid upstream response");
    return {
      statusCode: 200,
      headers: {
        "Content-Type": "application/x-ndjson",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-TollChat-Release": releaseId,
        "X-TollChat-Proxy": dependencies.proxyArn ?? "",
        "X-TollChat-Proxy-Version": dependencies.proxyVersion ?? "",
        "X-TollChat-Runtime": /** @type {string} */ (runtimeArn),
        "X-TollChat-Runtime-Version": dependencies.runtimeVersion ?? "",
        "X-TollChat-Endpoint": runtimeEndpoint,
        ...(cookie ? { "Set-Cookie": cookie } : {}),
      },
      body: ndjsonFromSse(
        /** @type {AsyncIterable<Uint8Array>} */ (result.response),
        release,
        canary,
      ),
    };
  } catch (error) {
    if (path === "/api/reset" && /** @type {Error | null} */ (error)?.name === "ResourceNotFoundException") {
      return json(200, { ok: true }, { "Set-Cookie": clearCookie });
    }
    await release();
    console.error("PROXY_FAILURE", "request", /** @type {Error | null} */ (error)?.name ?? "Error");
    return json(502, { error: SAFE_ERROR }, cookie ? { "Set-Cookie": cookie } : {});
  }
}

const client = new BedrockAgentCoreClient({
  region: process.env.AWS_REGION,
  endpoint: process.env.AGENTCORE_VPCE_URL,
});
const sessionClient = new DynamoDBClient({ region: process.env.AWS_REGION });
const deployed = Boolean(process.env.AWS_LAMBDA_RUNTIME_API);
/** @type {Dependencies | {}} */
const dependencies = deployed ? {
  client,
  sessionClient,
  sessionTable: process.env.SESSION_TABLE_NAME,
  now: Date.now,
  randomBytes,
  randomUUID,
  runtimeArn: process.env.AGENTCORE_RUNTIME_ARN,
  runtimeEndpoint: process.env.AGENTCORE_RUNTIME_ENDPOINT,
  releaseId: process.env.RELEASE_ID,
  runtimeVersion: process.env.AGENTCORE_RUNTIME_VERSION,
  proxyVersion: process.env.AWS_LAMBDA_FUNCTION_VERSION,
} : {};

export const handler = deployed ? globalThis.awslambda.streamifyResponse(async (event, responseStream, context) => {
  const response = await route(event, { .../** @type {Dependencies} */ (dependencies), proxyArn: context.invokedFunctionArn.split(":").slice(0, 7).join(":") });
  const stream = globalThis.awslambda.HttpResponseStream.from(responseStream, {
    statusCode: response.statusCode,
    headers: response.headers,
  });
  if (typeof response.body === "string") stream.write(response.body);
  else for await (const chunk of response.body) stream.write(chunk);
  stream.end();
}) : undefined;
