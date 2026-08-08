import { readFileSync } from "node:fs";
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
  StopRuntimeSessionCommand,
} from "@aws-sdk/client-bedrock-agentcore";

const MAX_MESSAGE_CHARS = 8_000;
const SAFE_ERROR = {
  type: "error",
  code: "agent_unavailable",
  message: "TollChat is temporarily unavailable. Please try again.",
};
const LABELS = new Set([
  "Planning toll route",
  "Checking I-66 tolls",
  "Checking I-95/395 tolls",
  "Checking I-95/395 Express Lanes access",
  "Checking I-95/395 Express Lanes tolls",
  "Checking I-495 tolls",
  "Checking Dulles tolls",
  "Checking toll data",
]);
const STATUS = new Set(["running", "completed", "failed"]);
const ERROR_CODES = new Set(["invalid_request", "turn_limit", "agent_unavailable"]);
const ERROR_MESSAGES = new Set([
  "Provide a message between 1 and 8000 characters.",
  "Start a new chat to continue.",
  "TollChat could not complete that request. Please try again.",
]);

const json = (statusCode, value) => ({
  statusCode,
  headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  body: JSON.stringify(value),
});

const invalid = () => json(400, {
  error: { code: "invalid_request", message: "Provide a valid chat session and message." },
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

const validSession = (value) =>
  typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

const exactKeys = (value, keys) =>
  Object.keys(value).sort().join(",") === [...keys].sort().join(",");

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

async function* ndjsonFromSse(stream) {
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
    yield `${JSON.stringify(terminal)}\n`;
  } catch {
    yield `${JSON.stringify(SAFE_ERROR)}\n`;
  }
}

export async function route(event, dependencies) {
  const { client, runtimeArn, previewHtml, previewJs = "", previewAssets = {} } = dependencies;
  const method = event.httpMethod;
  const path = event.path;
  if (method === "GET" && path === "/") {
    return { statusCode: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" }, body: previewHtml };
  }
  if (method === "GET" && path === "/preview.mjs") {
    return { statusCode: 200, headers: { "Content-Type": "text/javascript; charset=utf-8", "Cache-Control": "no-store" }, body: previewJs };
  }
  if (method === "GET" && Object.hasOwn(previewAssets, path)) {
    return { statusCode: 200, headers: { "Content-Type": "text/javascript; charset=utf-8", "Cache-Control": "public, max-age=31536000, immutable" }, body: previewAssets[path] };
  }
  if (method === "GET" && path === "/api/config") {
    return json(200, { chatEnabled: true, maxMessageChars: MAX_MESSAGE_CHARS, maxTurns: 5 });
  }
  if (method !== "POST" || !["/api/chat", "/api/reset"].includes(path)) {
    return json(404, { error: { code: "not_found" } });
  }
  const body = parseBody(event);
  if (!body || !validSession(body.session_id)) return invalid();
  try {
    if (path === "/api/reset") {
      await client.send(new StopRuntimeSessionCommand({
        agentRuntimeArn: runtimeArn,
        runtimeSessionId: body.session_id,
        qualifier: "preview",
      }));
      return json(200, { ok: true });
    }
    if (typeof body.message !== "string" || !body.message.trim() || body.message.trim().length > MAX_MESSAGE_CHARS) return invalid();
    const result = await client.send(new InvokeAgentRuntimeCommand({
      agentRuntimeArn: runtimeArn,
      runtimeSessionId: body.session_id,
      qualifier: "preview",
      payload: new TextEncoder().encode(JSON.stringify({ prompt: body.message.trim() })),
    }));
    if (!result.contentType?.includes("text/event-stream") || !result.response?.[Symbol.asyncIterator]) throw new Error("invalid upstream response");
    return {
      statusCode: 200,
      headers: { "Content-Type": "application/x-ndjson", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
      body: ndjsonFromSse(result.response),
    };
  } catch (error) {
    console.error("AgentCore request failed", error?.name ?? "Error");
    return json(502, { error: SAFE_ERROR });
  }
}

const client = new BedrockAgentCoreClient({
  region: process.env.AWS_REGION,
  endpoint: process.env.AGENTCORE_VPCE_URL,
});
const deployed = Boolean(process.env.AWS_LAMBDA_RUNTIME_API);
const dependencies = deployed ? {
  client,
  runtimeArn: process.env.AGENTCORE_RUNTIME_ARN,
  previewHtml: readFileSync(new URL("./preview.html", import.meta.url), "utf8"),
  previewJs: readFileSync(new URL("./preview.mjs", import.meta.url), "utf8"),
  previewAssets: {
    "/assets/chat-markdown-v1.mjs": readFileSync(new URL("./assets/chat-markdown-v1.mjs", import.meta.url), "utf8"),
    "/assets/markdown-it-15.0.0/markdown-it.esm.min.mjs": readFileSync(new URL("./assets/markdown-it-15.0.0/markdown-it.esm.min.mjs", import.meta.url), "utf8"),
  },
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
