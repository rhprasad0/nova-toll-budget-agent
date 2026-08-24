import { renderAssistantMarkdown } from "./assets/chat-markdown.mjs";

const SAFE_ERROR = {
  type: "error",
  code: "agent_unavailable",
  message: "TollChat is temporarily unavailable. Please try again.",
};
const TOOL_STATUSES = new Set(["running", "completed", "failed"]);
const STARTER_PROMPTS = Object.freeze([
  "What is the current price from Dumfries to Washington?",
  "How much take-home pay would I have after commuting from Leesburg to Washington on "
    + "Mondays and Fridays, leaving at 8:30 AM and returning at 5:30 PM for 96 days a "
    + "year, on a $130,000 gross annual salary?",
]);

export const post = async (path, body) => {
  const payload = JSON.stringify(body);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(payload));
  const hash = Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  return fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json", "x-amz-content-sha256": hash },
    body: payload,
  });
};

const validEvent = (event) => {
  if (!event || typeof event !== "object") return false;
  if (event.type === "tool") return Number.isInteger(event.index)
    && event.index >= 0 && typeof event.label === "string" && TOOL_STATUSES.has(event.status);
  if (event.type === "answer") return typeof event.text === "string"
    && typeof event.blocked === "boolean";
  return event.type === "error" && typeof event.code === "string"
    && typeof event.message === "string";
};

export async function consumeNdjson(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
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
      if (terminal) throw new Error("event after terminal");
      terminal = event.type === "answer" || event.type === "error";
      onEvent(event);
    }
    if (done) break;
  }
  if (buffer.trim()) throw new Error("incomplete stream event");
  if (!terminal) throw new Error("missing terminal event");
}

export const applyEvent = (view, event) => {
  if (event.type === "tool") {
    let item = view.items.get(event.index);
    if (!item) {
      item = view.createElement("li");
      item.append(view.createElement("span"), view.createElement("span"));
      view.activities.append(item);
      view.items.set(event.index, item);
    }
    item.dataset.status = event.status;
    item.children[0].textContent = event.label;
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
    view.answer.textContent = event.message;
    view.answer.className = "answer error";
  } else {
    view.answer.className = event.blocked ? "answer error" : "answer";
    view.answer.innerHTML = renderAssistantMarkdown(event.text);
  }
  view.article?.scrollIntoView({ block: "end" });
};

export async function runRequest(request, onEvent, setBusy, onSessionExpired = () => {}) {
  setBusy(true);
  try {
    await request(onEvent);
  } catch (error) {
    if (error?.code === "session_expired") onSessionExpired(error);
    else onEvent(SAFE_ERROR);
  } finally {
    setBusy(false);
  }
}

export const shouldSubmitOnEnter = (event, busy) => event.key === "Enter"
  && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && !busy;

export const usageProofText = (snapshot, now = Date.now()) => {
  if (!snapshot || typeof snapshot !== "object"
    || snapshot.schema_version !== 1
    || !/^\d{4}-\d{2}-\d{2}$/.test(snapshot.collection_started_on)
    || !Number.isInteger(snapshot.engaged_sessions) || snapshot.engaged_sessions < 0
    || !Number.isInteger(snapshot.completed_responses) || snapshot.completed_responses < 0) return null;
  const started = Date.parse(`${snapshot.collection_started_on}T00:00:00Z`);
  const asOf = Date.parse(snapshot.as_of);
  if (!Number.isFinite(started) || !Number.isFinite(asOf) || started > asOf
    || asOf > now + 5 * 60_000 || now - asOf > 48 * 60 * 60_000) return null;
  const format = new Intl.DateTimeFormat("en-US", {
    month: "long", day: "numeric", timeZone: "UTC",
  });
  const sessions = snapshot.engaged_sessions === 1 ? "session" : "sessions";
  const responses = snapshot.completed_responses === 1 ? "response" : "responses";
  return `Since ${format.format(started)}, ${snapshot.engaged_sessions} counted anonymous chat ${sessions} sent a message and received ${snapshot.completed_responses} completed ${responses}. Updated daily; last updated ${format.format(asOf)}.`;
};

const newTurn = (transcript) => {
  const article = document.createElement("article");
  article.className = "assistant-turn";
  const activities = document.createElement("ol");
  activities.className = "activities";
  activities.setAttribute("aria-label", "Tool activity");
  const answer = document.createElement("div");
  answer.className = "answer";
  answer.setAttribute("aria-live", "polite");
  article.append(activities, answer);
  transcript.append(article);
  return {
    article,
    activities,
    answer,
    items: new Map(),
    createElement: document.createElement.bind(document),
  };
};

const responseError = async (response) => {
  const data = await response.json().catch(() => ({}));
  const error = new Error(data.error?.message || SAFE_ERROR.message);
  error.code = data.error?.code;
  return error;
};

const start = () => {
  const transcript = document.querySelector("#transcript");
  const form = document.querySelector("#chat");
  const input = document.querySelector("#message");
  const submit = form.querySelector("button");
  const reset = document.querySelector("#reset");
  const starterWrap = document.querySelector("#starter-wrap");
  const usageProof = document.querySelector("#usage-proof");
  const starterButtons = [...document.querySelectorAll("[data-prompt-index]")];
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

  void fetch("/usage.json", { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("usage snapshot unavailable");
      return response.json();
    })
    .then((snapshot) => {
      const text = usageProofText(snapshot);
      if (!text) return;
      usageProof.textContent = text;
      usageProof.hidden = false;
    })
    .catch(() => {});

  for (const button of starterButtons) {
    button.addEventListener("click", () => {
      input.value = STARTER_PROMPTS[Number(button.dataset.promptIndex)];
      form.requestSubmit();
    });
  }

  if (!navigator.locks) {
    setBusy(true);
    applyEvent(newTurn(transcript), {
      type: "error",
      code: "unsupported_browser",
      message: "This browser cannot securely open TollChat.",
    });
  } else {
    setBusy(true);
    void navigator.locks.request("tollchat-active-session", { ifAvailable: true }, async (lock) => {
      if (!lock) {
        applyEvent(newTurn(transcript), {
          type: "error",
          code: "session_busy",
          message: "TollChat is open in another tab.",
        });
        return;
      }
      const response = await post("/api/reset", {}).catch(() => null);
      if (!response?.ok) {
        const error = response ? await responseError(response) : SAFE_ERROR;
        if (error.code !== "session_expired") {
          applyEvent(newTurn(transcript), SAFE_ERROR);
          return;
        }
      }
      transcript.replaceChildren();
      setBusy(false);
      await new Promise(() => {});
    });
  }

  input.addEventListener("keydown", (event) => {
    if (!shouldSubmitOnEnter(event, form.getAttribute("aria-busy") === "true")) return;
    event.preventDefault();
    form.requestSubmit();
  });

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
    starterWrap.hidden = true;
    runRequest(async (onEvent) => {
      const response = await post("/api/chat", { message });
      if (!response.ok || !response.body) throw await responseError(response);
      await consumeNdjson(response.body, onEvent);
    }, (item) => applyEvent(view, item), setBusy, (error) => {
      transcript.replaceChildren();
      applyEvent(newTurn(transcript), {
        type: "error", code: error.code, message: error.message,
      });
    });
  });

  reset.addEventListener("click", async () => {
    setBusy(true);
    try {
      const response = await post("/api/reset", {});
      if (!response.ok) {
        const error = await responseError(response);
        if (error.code !== "session_expired") throw error;
      }
      transcript.replaceChildren();
      starterWrap.hidden = false;
    } catch {
      applyEvent(newTurn(transcript), SAFE_ERROR);
    } finally {
      setBusy(false);
      input.focus();
    }
  });
};

if (typeof document !== "undefined") start();
