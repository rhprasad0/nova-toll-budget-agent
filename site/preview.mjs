import { renderAssistantMarkdown } from "./assets/chat-markdown-v1.mjs";

const SAFE_ERROR = {
  type: "error",
  code: "agent_unavailable",
  message: "TollChat is temporarily unavailable. Please try again.",
};
const TOOL_STATUS = new Set(["running", "completed", "failed"]);

const validEvent = (event) => {
  if (!event || typeof event !== "object") return false;
  if (event.type === "tool") return Number.isInteger(event.index)
    && event.index >= 0 && typeof event.label === "string" && TOOL_STATUS.has(event.status);
  if (event.type === "answer") return typeof event.text === "string" && typeof event.blocked === "boolean";
  return event.type === "error" && typeof event.code === "string" && typeof event.message === "string";
};

export function applyEvent(view, event) {
  if (event.type === "tool") {
    let item = view.items.get(event.index);
    if (!item) {
      item = view.createElement("li");
      const label = view.createElement("span");
      const status = view.createElement("span");
      label.textContent = event.label;
      status.className = "activity-status";
      item.append(label, status);
      view.activities.append(item);
      view.items.set(event.index, item);
    }
    item.dataset.status = event.status;
    item.children[1].textContent = event.status[0].toUpperCase() + event.status.slice(1);
    return;
  }
  if (event.type === "error") {
    for (const item of view.items.values()) {
      if (item.dataset.status === "running") {
        item.dataset.status = "failed";
        item.children[1].textContent = "Failed";
      }
    }
  }
  view.answer.className = event.type === "answer" && !event.blocked
    ? "assistant-answer"
    : "assistant-answer assistant-answer--notice";
  if (event.type === "answer") view.answer.innerHTML = renderAssistantMarkdown(event.text);
  else view.answer.textContent = event.message;
}

export async function consumeNdjson(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const event = JSON.parse(line);
      if (!validEvent(event)) throw new Error("invalid stream event");
      onEvent(event);
    }
    if (done) break;
  }
  if (buffer.trim()) throw new Error("incomplete stream event");
}

export async function runRequest(request, onEvent, setBusy) {
  setBusy(true);
  try {
    await request(onEvent);
  } catch {
    onEvent(SAFE_ERROR);
  } finally {
    setBusy(false);
  }
}

const sessionId = () => crypto.randomUUID();

function newTurn(container) {
  const article = document.createElement("article");
  article.className = "assistant-turn";
  const activities = document.createElement("ol");
  activities.className = "activities";
  activities.setAttribute("aria-label", "Toll lookup activity");
  const answer = document.createElement("p");
  answer.className = "assistant-answer";
  article.append(activities, answer);
  container.append(article);
  return { activities, answer, items: new Map(), createElement: document.createElement.bind(document) };
}

function start() {
  const form = document.querySelector("form");
  if (!form) return;
  const input = document.querySelector("textarea");
  const submit = form.querySelector("button");
  const reset = document.querySelector("#reset");
  const transcript = document.querySelector("#transcript");
  let session = sessionId();
  const setBusy = (busy) => {
    submit.disabled = busy;
    input.disabled = busy;
    form.setAttribute("aria-busy", String(busy));
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    const user = document.createElement("p");
    user.className = "user-turn";
    user.textContent = message;
    transcript.append(user);
    const view = newTurn(transcript);
    input.value = "";
    runRequest(async (onEvent) => {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: session, message }),
      });
      if (!response.ok || !response.body) throw new Error("request failed");
      await consumeNdjson(response.body, onEvent);
    }, (item) => applyEvent(view, item), setBusy);
  });

  reset.addEventListener("click", async () => {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: session }),
    }).catch(() => {});
    session = sessionId();
    transcript.replaceChildren();
    input.focus();
  });
}

if (typeof document !== "undefined") start();
