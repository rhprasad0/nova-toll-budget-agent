import { createHash, randomBytes, randomUUID } from "node:crypto";
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
  StopRuntimeSessionCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import { DynamoDBClient, PutItemCommand, UpdateItemCommand } from "@aws-sdk/client-dynamodb";

const MAX_MESSAGE_CHARS = 8_000;
const IDLE_SECONDS = 15 * 60;
const MAX_SESSION_SECONDS = 60 * 60;
const LEASE_SECONDS = 60;
const COOKIE = "__Host-tollchat-session";
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const PUBLIC_ORIGINS = new Set(["https://tollchat.ai", "https://www.tollchat.ai"]);
const DRILL_MODE = "runtime_exception_v2";
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
const expired = () => json(401, {
  error: { code: "session_expired", message: "Your chat expired. Please send your question again." },
}, { "Set-Cookie": clearCookie });
const busy = () => json(409, {
  error: { code: "session_busy", message: "Wait for the current response to finish." },
});

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

const exactKeys = (value, keys) =>
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");

const header = (event, name) => Object.entries(event.headers ?? {})
  .find(([key]) => key.toLowerCase() === name)?.[1];

const validPost = (event) => {
  const contentType = header(event, "content-type")?.split(";", 1)[0].trim().toLowerCase();
  try {
    const origin = new URL(header(event, "origin"));
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

const credential = (event) => {
  const values = [];
  const sources = event.cookies?.length ? event.cookies : [header(event, "cookie") ?? ""];
  for (const source of sources.filter(Boolean)) {
    for (const part of source.split(";")) {
      const [name, ...raw] = part.trim().split("=");
      if (name === COOKIE) values.push(raw.join("="));
    }
  }
  if (!values.length) return { kind: "missing" };
  if (values.length !== 1 || !TOKEN.test(values[0])) return { kind: "invalid" };
  return { kind: "valid", token: values[0] };
};

const tokenHash = (token) => createHash("sha256").update(token).digest("hex");
const sessionCookie = (token) =>
  `${COOKIE}=${token}; Path=/; Max-Age=${MAX_SESSION_SECONDS}; HttpOnly; Secure; SameSite=Strict`;

const conditionalFailure = (error) => error?.name === "ConditionalCheckFailedException";

const createSession = async (dependencies, leaseId) => {
  const now = Math.floor(dependencies.now() / 1000);
  const token = dependencies.randomBytes(32).toString("base64url");
  const runtimeSessionId = dependencies.randomUUID();
  await dependencies.sessionClient.send(new PutItemCommand({
    TableName: dependencies.sessionTable,
    Item: {
      credential_hash: { S: tokenHash(token) },
      runtime_session_id: { S: runtimeSessionId },
      created_at: { N: String(now) },
      last_seen_at: { N: String(now) },
      expires_at: { N: String(now + MAX_SESSION_SECONDS) },
      lease_id: { S: leaseId },
      lease_until: { N: String(now + LEASE_SECONDS) },
    },
    ConditionExpression: "attribute_not_exists(credential_hash)",
  }));
  return { runtimeSessionId, token, cookie: sessionCookie(token) };
};

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
        "expires_at > :now",
        "last_seen_at > :idle_cutoff",
        "(attribute_not_exists(lease_until) OR lease_until <= :now)",
      ].join(" AND "),
      ExpressionAttributeValues: {
        ":now": { N: String(now) },
        ":idle_cutoff": { N: String(now - IDLE_SECONDS) },
        ...(acquiring ? {
          ":lease_id": { S: leaseId },
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
      const activeLease = Number(item?.lease_until?.N) > now;
      const current = Number(item?.expires_at?.N) > now
        && Number(item?.last_seen_at?.N) > now - IDLE_SECONDS
        && !item?.revoked_at;
      return { kind: current && activeLease ? "busy" : "expired" };
    }
    throw error;
  }
};

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
    if (!conditionalFailure(error)) console.error("PROXY_FAILURE", "lease_release", error?.name ?? "Error");
  }
};

const validEvent = (value) => {
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
  return value.type === "error"
    && exactKeys(value, ["type", "code", "message"])
    && ERROR_CODES.has(value.code) && ERROR_MESSAGES.has(value.message);
};

async function* ndjsonFromSse(stream, release = async () => {}) {
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
        const value = JSON.parse(lines.map((line) => line.slice(6)).join("\n"));
        if (!validEvent(value)) throw new Error("invalid stream event");
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
    console.error("PROXY_FAILURE", "stream", error?.name ?? "Error");
    yield `${JSON.stringify(SAFE_ERROR)}\n`;
  } finally {
    await release();
  }
}

export async function route(event, dependencies) {
  const { client, runtimeArn } = dependencies;
  const method = event.httpMethod ?? event.requestContext?.http?.method;
  const path = event.path ?? event.rawPath;
  if (method === "GET" && path === "/api/config") {
    return json(200, { chatEnabled: true, maxMessageChars: MAX_MESSAGE_CHARS, maxTurns: 5 });
  }
  if (method !== "POST" || !["/api/chat", "/api/reset"].includes(path)) {
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
      if (session.kind === "expired") return expired();
      cookie = clearCookie;
      await client.send(new StopRuntimeSessionCommand({
        agentRuntimeArn: runtimeArn,
        runtimeSessionId: session.runtimeSessionId,
        qualifier: "preview",
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
      if (session.kind === "expired") return expired();
      runtimeSessionId = session.runtimeSessionId;
      sessionToken = supplied.token;
    }
    let leaseHeld = true;
    release = async () => {
      if (!leaseHeld) return;
      leaseHeld = false;
      await releaseSession(dependencies, sessionToken, leaseId);
    };
    const result = await client.send(new InvokeAgentRuntimeCommand({
      agentRuntimeArn: runtimeArn,
      runtimeSessionId,
      qualifier: "preview",
      payload: new TextEncoder().encode(JSON.stringify({
        prompt: body.message.trim(),
        ...(validPost(event)
          && header(event, "x-tollchat-drill") === "runtime-exception-v2"
          ? { failure_mode: DRILL_MODE }
          : {}),
      })),
    }));
    if (!result.contentType?.includes("text/event-stream") || !result.response?.[Symbol.asyncIterator]) throw new Error("invalid upstream response");
    return {
      statusCode: 200,
      headers: {
        "Content-Type": "application/x-ndjson",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        ...(cookie ? { "Set-Cookie": cookie } : {}),
      },
      body: ndjsonFromSse(result.response, release),
    };
  } catch (error) {
    if (path === "/api/reset" && error?.name === "ResourceNotFoundException") {
      return json(200, { ok: true }, { "Set-Cookie": clearCookie });
    }
    await release();
    console.error("PROXY_FAILURE", "request", error?.name ?? "Error");
    return json(502, { error: SAFE_ERROR }, cookie ? { "Set-Cookie": cookie } : {});
  }
}

const client = new BedrockAgentCoreClient({
  region: process.env.AWS_REGION,
  endpoint: process.env.AGENTCORE_VPCE_URL,
});
const sessionClient = new DynamoDBClient({ region: process.env.AWS_REGION });
const deployed = Boolean(process.env.AWS_LAMBDA_RUNTIME_API);
const dependencies = deployed ? {
  client,
  sessionClient,
  sessionTable: process.env.SESSION_TABLE_NAME,
  now: Date.now,
  randomBytes,
  randomUUID,
  runtimeArn: process.env.AGENTCORE_RUNTIME_ARN,
} : {};

export const handler = deployed ? globalThis.awslambda.streamifyResponse(async (event, responseStream) => {
  const response = await route(event, dependencies);
  const stream = globalThis.awslambda.HttpResponseStream.from(responseStream, {
    statusCode: response.statusCode,
    headers: response.headers,
  });
  if (typeof response.body === "string") stream.write(response.body);
  else for await (const chunk of response.body) stream.write(chunk);
  stream.end();
}) : undefined;
