import { renderAssistantMarkdown } from "./assets/chat-markdown.mjs";

const TOOL_STATUSES = new Set(["running", "completed", "failed"]);
export const MAX_RAW_EVENT_LOG_CHARS = 64 * 1024;
const RAW_EVENT_LOG_TRUNCATED = "Earlier events omitted.\n";
export const STARTER_PROMPTS = Object.freeze([
  "What is the current price from Dumfries to Washington?",
  "How much take-home pay would I have after commuting from Leesburg to Washington on "
    + "Mondays and Fridays, leaving at 8:30 AM and returning at 5:30 PM for 96 days a "
    + "year, on a $130,000 gross annual salary?",
]);

export const validStreamEvent = (event) => {
  if (!event || typeof event !== "object" || !Number.isInteger(event.sequence) || event.sequence < 0) {
    return false;
  }
  if (event.type === "error") return typeof event.message === "string";
  if (event.type !== "event" || !event.event || typeof event.event !== "object") return false;
  if (event.text_delta !== undefined && typeof event.text_delta !== "string") return false;
  if (event.tool_updates !== undefined && (!Array.isArray(event.tool_updates)
    || event.tool_updates.some((tool) => !Number.isInteger(tool.index)
      || tool.index < 0 || typeof tool.label !== "string" || !TOOL_STATUSES.has(tool.status)))) {
    return false;
  }
  return event.final === undefined || (event.final && typeof event.final.text === "string"
    && event.final.metrics && typeof event.final.metrics === "object");
};

export async function consumeNdjson(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  let sequence = 0;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const event = JSON.parse(line);
      if (!validStreamEvent(event)) throw new Error("invalid stream event");
      if (event.sequence !== sequence++) throw new Error("out-of-order stream event");
      if (terminal) throw new Error("event after terminal");
      terminal = event.type === "error" || event.final !== undefined;
      onEvent(event);
    }
    if (done) break;
  }
  if (buffer.trim()) throw new Error("incomplete stream event");
  if (!terminal) throw new Error("missing terminal event");
}

const request = (path, body) => fetch(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const newTurn = (transcript) => {
  const article = document.createElement("article");
  article.className = "assistant-turn";
  const activities = document.createElement("ol");
  activities.className = "activities";
  activities.setAttribute("aria-label", "Tool activity");
  const answer = document.createElement("div");
  answer.className = "answer";
  answer.setAttribute("aria-live", "polite");
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Technical details (Strands events)";
  const raw = document.createElement("pre");
  details.append(summary, raw);
  article.append(activities, answer, details);
  transcript.append(article);
  const view = {
    article,
    activities,
    answer,
    details,
    raw,
    rawChars: 0,
    rawEvents: [],
    rawTruncated: false,
    items: new Map(),
    renderFrame: null,
    text: "",
  };
  details.addEventListener("toggle", () => {
    raw.textContent = details.open
      ? `${view.rawTruncated ? RAW_EVENT_LOG_TRUNCATED : ""}${view.rawEvents.join("")}`
      : "";
  });
  return view;
};

const appendRawEvent = (view, event) => {
  const line = `${JSON.stringify(event, null, 2)}\n`;
  view.rawEvents.push(line);
  view.rawChars += line.length;
  if (view.rawTruncated || view.rawChars > MAX_RAW_EVENT_LOG_CHARS) {
    view.rawTruncated = true;
    let overflow = view.rawChars
      - (MAX_RAW_EVENT_LOG_CHARS - RAW_EVENT_LOG_TRUNCATED.length);
    // ponytail: Array.shift stays bounded by the 64 KiB log cap.
    while (overflow > 0) {
      const first = view.rawEvents[0];
      if (first.length <= overflow) {
        view.rawEvents.shift();
        view.rawChars -= first.length;
        overflow -= first.length;
      } else {
        view.rawEvents[0] = first.slice(overflow);
        view.rawChars -= overflow;
        overflow = 0;
      }
    }
  }
  if (view.details.open) {
    view.raw.textContent = `${view.rawTruncated ? RAW_EVENT_LOG_TRUNCATED : ""}`
      + view.rawEvents.join("");
  }
};

const flushMarkdown = (view) => {
  view.renderFrame = null;
  view.answer.innerHTML = renderAssistantMarkdown(view.text);
  view.article.scrollIntoView({ block: "end" });
};

const cancelMarkdown = (view) => {
  if (view.renderFrame !== null) cancelAnimationFrame(view.renderFrame);
  view.renderFrame = null;
};

const queueMarkdown = (view) => {
  if (view.renderFrame === null) {
    view.renderFrame = requestAnimationFrame(() => flushMarkdown(view));
  }
};

export const applyEvent = (view, event) => {
  appendRawEvent(view, event);
  for (const tool of event.tool_updates || []) {
    let item = view.items.get(tool.index);
    if (!item) {
      item = document.createElement("li");
      item.append(document.createElement("span"), document.createElement("span"));
      view.activities.append(item);
      view.items.set(tool.index, item);
    }
    item.dataset.status = tool.status;
    item.children[0].textContent = tool.label;
    item.children[1].textContent = tool.status[0].toUpperCase() + tool.status.slice(1);
  }
  if (event.type === "error") {
    cancelMarkdown(view);
    for (const item of view.items.values()) {
      if (item.dataset.status === "running") {
        item.dataset.status = "failed";
        item.children[1].textContent = "Failed";
      }
    }
    view.answer.textContent = event.message;
    view.answer.classList.add("error");
    view.article.scrollIntoView({ block: "end" });
    return;
  }
  if (event.final) {
    cancelMarkdown(view);
    view.text = event.final.text;
    flushMarkdown(view);
    return;
  }
  if (event.text_delta !== undefined) {
    view.text += event.text_delta;
    queueMarkdown(view);
    return;
  }
  view.article.scrollIntoView({ block: "end" });
};

const start = () => {
  const transcript = document.querySelector("#transcript");
  const form = document.querySelector("#chat");
  const input = document.querySelector("#message");
  const submit = form.querySelector("button");
  const reset = document.querySelector("#reset");
  const starterWrap = document.querySelector("#starter-wrap");
  const starterButtons = [...document.querySelectorAll("[data-prompt-index]")];
  const sessionId = sessionStorage.tollchatV2SessionId ||= crypto.randomUUID();
  const setBusy = (busy) => {
    input.disabled = busy;
    submit.disabled = busy;
    reset.disabled = busy;
    for (const button of starterButtons) button.disabled = busy;
    form.setAttribute("aria-busy", String(busy));
  };

  import("./assets/commute-map.mjs")
    .then(({ mountCommuteMap }) => mountCommuteMap())
    .catch((error) => {
      console.error("TollChat map failed", error);
      document.querySelector("#map-loading").hidden = true;
      document.querySelector("#map-error").hidden = false;
    });

  for (const button of starterButtons) {
    button.addEventListener("click", () => {
      input.value = STARTER_PROMPTS[Number(button.dataset.promptIndex)];
      form.requestSubmit();
    });
  }

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    form.requestSubmit();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    const user = document.createElement("p");
    user.className = "user-turn";
    user.textContent = message;
    transcript.append(user);
    const view = newTurn(transcript);
    input.value = "";
    starterWrap.hidden = true;
    setBusy(true);
    try {
      const response = await request("/api/chat", { session_id: sessionId, message });
      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || "TollChat couldn't send your question. Please try again.");
      }
      await consumeNdjson(response.body, (item) => applyEvent(view, item));
    } catch (error) {
      applyEvent(view, {
        type: "error",
        sequence: 0,
        message: error.message || "TollChat couldn't send your question. Please try again.",
      });
    } finally {
      setBusy(false);
      input.focus();
    }
  });

  reset.addEventListener("click", async () => {
    setBusy(true);
    try {
      const response = await request("/api/reset", { session_id: sessionId });
      if (!response.ok) throw new Error("TollChat couldn't start a new chat. Please try again.");
      transcript.replaceChildren();
      starterWrap.hidden = false;
    } catch (error) {
      const view = newTurn(transcript);
      applyEvent(view, { type: "error", sequence: 0, message: error.message });
    } finally {
      setBusy(false);
      input.focus();
    }
  });
};

if (typeof document !== "undefined") start();
