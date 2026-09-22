/** @typedef {{type: "tool", index: number, label: string, status: string} | {type: "text", text: string} | {type: "answer", text: string, blocked: boolean} | {type: "error", code: string, message: string}} PublicEvent */
/** @typedef {HTMLElement} PublicElement */
/** @typedef {{activities: {append(...nodes: PublicElement[]): void}, answer: {innerHTML: string, textContent: string | null, className: string}, article?: Pick<HTMLElement, "scrollIntoView" | "getBoundingClientRect">, items: Map<number, PublicElement>, createElement(tag: string): PublicElement}} TurnView */
/** @typedef {Error & {code?: string}} ResponseError */
import { renderAssistantMarkdown } from "./assets/chat-markdown.mjs";

/** @type {PublicEvent} */
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

/** @param {string} path @param {object} body */
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

/** @param {unknown} input @returns {input is PublicEvent} */
const validEvent = (input) => {
  const event = /** @type {PublicEvent} */ (input);
  if (!event || typeof event !== "object") return false;
  if (event.type === "tool") return Number.isInteger(event.index)
    && event.index >= 0 && typeof event.label === "string" && TOOL_STATUSES.has(event.status);
  if (event.type === "text") return Object.keys(event).length === 2
    && typeof event.text === "string" && event.text.length > 0;
  if (event.type === "answer") return typeof event.text === "string"
    && typeof event.blocked === "boolean";
  return event.type === "error" && typeof event.code === "string"
    && typeof event.message === "string";
};

/** @param {ReadableStream<Uint8Array>} stream @param {(event: PublicEvent) => void} onEvent */
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
      /** @type {unknown} */
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

/** @param {TurnView} view @param {PublicEvent} event */
export const applyEvent = (view, event) => {
  const article = view.article;
  const follow = article && article.getBoundingClientRect().bottom <= window.innerHeight + 24;
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
  } else if (event.type === "error") {
    for (const item of view.items.values()) {
      if (item.dataset.status === "running") {
        item.dataset.status = "failed";
        item.children[1].textContent = "Failed";
      }
    }
    view.answer.textContent = event.message;
    view.answer.className = "answer error";
  } else {
    view.answer.className = event.type === "answer" && event.blocked ? "answer error" : "answer";
    view.answer.innerHTML = renderAssistantMarkdown(event.text);
  }
  // Follow growth without pulling visible text upward or interrupting a reader.
  if (follow && article.getBoundingClientRect().bottom > window.innerHeight) {
    article.scrollIntoView({ block: "end", behavior: "instant" });
  }
};

/** @param {(onEvent: (event: PublicEvent) => void) => Promise<void>} request @param {(event: PublicEvent) => void} onEvent @param {(busy: boolean) => void} setBusy @param {(error: ResponseError) => void} onSessionExpired */
export async function runRequest(request, onEvent, setBusy, onSessionExpired = () => {}) {
  setBusy(true);
  try {
    await request(onEvent);
  } catch (error) {
    if (/** @type {ResponseError | null} */ (error)?.code === "session_expired") onSessionExpired(/** @type {ResponseError} */ (error));
    else onEvent(SAFE_ERROR);
  } finally {
    setBusy(false);
  }
}

/** @param {Pick<KeyboardEvent, "key" | "shiftKey" | "isComposing"> & {keyCode?: number}} event @param {boolean} busy */
export const shouldSubmitOnEnter = (event, busy) => event.key === "Enter"
  && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && !busy;

/** @param {HTMLElement} transcript @returns {TurnView} */
const newTurn = (transcript) => {
  const article = document.createElement("article");
  article.className = "assistant-turn";
  const activities = document.createElement("ol");
  activities.className = "activities";
  activities.setAttribute("aria-label", "Tool activity");
  const answer = document.createElement("div");
  answer.className = "answer";
  answer.setAttribute("aria-live", "polite");
  answer.textContent = "Working…";
  article.append(activities, answer);
  transcript.append(article);
  article.scrollIntoView({ block: "nearest", behavior: "instant" });
  return {
    article,
    activities,
    answer,
    items: new Map(),
    createElement: document.createElement.bind(document),
  };
};

/** @param {Response} response */
const responseError = async (response) => {
  const data = await response.json().catch(() => ({}));
  const error = /** @type {ResponseError} */ (new Error(data.error?.message || SAFE_ERROR.message));
  error.code = data.error?.code;
  return error;
};

const start = () => {
  const transcript = /** @type {HTMLElement} */ (document.querySelector("#transcript"));
  const form = /** @type {HTMLFormElement} */ (document.querySelector("#chat"));
  const input = /** @type {HTMLTextAreaElement} */ (document.querySelector("#message"));
  const submit = /** @type {HTMLButtonElement} */ (form.querySelector('button[type="submit"]'));
  const reset = /** @type {HTMLButtonElement} */ (document.querySelector("#reset"));
  const starterWrap = /** @type {HTMLElement} */ (document.querySelector("#starter-wrap"));
  const starterButtons = [.../** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-prompt-index]"))];
  /** @param {boolean} busy */
  const setBusy = (busy) => {
    input.disabled = busy;
    submit.disabled = busy;
    reset.disabled = busy;
    for (const button of starterButtons) button.disabled = busy;
    form.setAttribute("aria-busy", String(busy));
  };

  const mapWatchdog = setTimeout(() => {
    /** @type {HTMLElement} */ (document.querySelector("#map-loading")).hidden = true;
    /** @type {HTMLElement} */ (document.querySelector("#map-error")).hidden = false;
  }, 12000);
  import("./assets/commute-map.mjs")
    .then(({ mountCommuteMap }) => mountCommuteMap(mapWatchdog))
    .catch((error) => {
      clearTimeout(mapWatchdog);
      console.error("TollChat map failed", error);
      /** @type {HTMLElement} */ (document.querySelector("#map-loading")).hidden = true;
      /** @type {HTMLElement} */ (document.querySelector("#map-error")).hidden = false;
    });

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
      let expired;
      if (!response?.ok) {
        const error = response ? await responseError(response) : SAFE_ERROR;
        if (error.code !== "session_expired") {
          applyEvent(newTurn(transcript), SAFE_ERROR);
          return;
        }
        expired = error;
      }
      transcript.replaceChildren();
      if (expired) applyEvent(newTurn(transcript), { type: "error", code: /** @type {string} */ (expired.code), message: expired.message });
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
    starterWrap.hidden = true;
    const view = newTurn(transcript);
    input.value = "";
    runRequest(async (onEvent) => {
      const response = await post("/api/chat", { message });
      if (!response.ok || !response.body) throw await responseError(response);
      await consumeNdjson(response.body, onEvent);
    }, (item) => applyEvent(view, item), setBusy, (error) => {
      transcript.replaceChildren();
      applyEvent(newTurn(transcript), {
        type: "error", code: /** @type {string} */ (error.code), message: error.message,
      });
    });
  });

  reset.addEventListener("click", async () => {
    setBusy(true);
    try {
      const response = await post("/api/reset", {});
      let expired;
      if (!response.ok) {
        const error = await responseError(response);
        if (error.code !== "session_expired") throw error;
        expired = error;
      }
      transcript.replaceChildren();
      if (expired) applyEvent(newTurn(transcript), { type: "error", code: /** @type {string} */ (expired.code), message: expired.message });
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
