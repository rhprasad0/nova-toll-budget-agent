const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const labels = {
  passed: "Passed",
  failed: "Failed",
  error: "Execution error",
  running: "In progress",
  overdue: "No completed result",
  stale: "Arrived too late",
  waiting: "Awaiting first run",
};
const checkLabels = {
  ToolCallCount: "One pricing lookup per turn",
  Completeness: "Answered the request",
  Correctness: "Supported by evidence",
};
const date = (value) =>
  new Date(value).toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
const badge = (status) =>
  `<span class="badge ${status}"><i class="dot" aria-hidden="true"></i>${labels[status]}</span>`;
const expectedEnvironment = $('meta[name="eval-environment"]').content;
const key = (r) => `${r.window_id}/${r.scheduled_at}`;
const instantKey = (r) => `${r.window_id}/${Date.parse(r.scheduled_at)}`;
let snapshot;
let failedRefresh = false;
let refreshing = false;

function outcome(r) {
  return r.status === "running" &&
    Date.now() > Date.parse(r.scheduled_at) + 25 * 60000
    ? "overdue"
    : r.status;
}
function evidence(r) {
  const e = r.evidence || {};
  const turns = (e.turns || [])
    .map(
      (turn) =>
        `<div class="bubble"><span class="speaker">Simulated user</span>${escapeHtml(turn.user)}</div><div class="bubble assistant"><span class="speaker">TollChat</span>${escapeHtml(turn.assistant)}</div>${(turn.tools || []).map((tool) => `<details><summary>Pricing lookup evidence</summary><pre>${escapeHtml(JSON.stringify(tool, null, 2))}</pre></details>`).join("")}`,
    )
    .join("");
  const checks = (e.checks || [])
    .map(
      (c) =>
        `<div class="check"><div class="check-line"><span>${checkLabels[c.name]}</span><span class="${c.passed ? "green" : "red"}">${c.passed ? "Passed" : "Failed"}</span></div><p>${escapeHtml(c.reason)}</p></div>`,
    )
    .join("");
  return `<div class="evidence"><h4>Recorded conversation</h4>${turns || "<p>No completed conversation was recorded.</p>"}<h4>Checks</h4>${checks || "<p>Not scored. An interrupted or late run is not a passing evaluation.</p>"}<p class="tool-evidence">Application, simulated user, and judges: ${escapeHtml(e.model || "gpt-5.6-luna")}. Internal diagnostics are omitted from public evidence.</p></div>`;
}

function render() {
  if (!snapshot) return;
  const opened = new Set(
    [...document.querySelectorAll("details[open][data-key]")].map(
      (el) => el.dataset.key,
    ),
  );
  const cutoff = Date.now() - 7 * 86400000;
  const runs = snapshot.runs.filter(
    (r) => Date.parse(r.scheduled_at) >= cutoff,
  );
  const occupied = new Set(snapshot.runs.map(instantKey));
  const missed = snapshot.schedule.filter(
    (s) =>
      Date.parse(s.scheduled_at) >= cutoff &&
      Date.parse(s.scheduled_at) < Date.now() - 25 * 60000 &&
      !occupied.has(instantKey(s)),
  );
  const passes = runs.filter((r) => r.status === "passed").length;
  const failures = runs.filter((r) => r.status === "failed").length;
  const errors = runs.filter((r) =>
    ["error", "stale", "overdue"].includes(outcome(r)),
  ).length;
  const graded = passes + failures;
  const future = snapshot.schedule
    .filter((s) => Date.parse(s.scheduled_at) > Date.now())
    .sort((a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at))[0];
  $("#environment").textContent =
    `${snapshot.environment.toUpperCase()} · REAL SCHEDULED RESULTS`;
  const awaiting = missed.length || runs.some((r) => outcome(r) === "overdue");
  $("#freshness").textContent = failedRefresh
    ? "Refresh failed. Showing the last received snapshot."
    : awaiting
      ? "An expected result is missing or incomplete. See run history."
      : future
        ? `Next scheduled run: ${date(future.scheduled_at)}`
        : "Schedule snapshot is out of date. Waiting for a new publication.";
  $("#updated").textContent = `Published ${date(snapshot.generated_at)}`;
  $("#metrics").innerHTML = [
    [
      "Graded runs passed",
      `${passes} <small>of ${graded}</small>`,
      graded
        ? `${Math.round((passes / graded) * 100)}% · execution errors excluded`
        : "No completed, graded runs yet",
    ],
    [
      "Graded runs failed",
      failures,
      "Completed runs that did not meet all checks",
    ],
    [
      "Errors / incomplete",
      errors + missed.length,
      "Execution errors, late or missing results",
    ],
    [
      "Scenarios exercised",
      `${new Set(runs.map((r) => r.scenario_id)).size} <small>of ${snapshot.scenarios.length}</small>`,
      "Recorded attempts in the last seven days",
    ],
  ]
    .map(
      ([label, value, note]) =>
        `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></div>`,
    )
    .join("");
  $("#ticks").innerHTML = [...runs]
    .reverse()
    .map(
      (r) =>
        `<span class="tick ${outcome(r)}" title="${date(r.scheduled_at)}: ${labels[outcome(r)]}"><span class="sr-only">${date(r.scheduled_at)}: ${labels[outcome(r)]}</span></span>`,
    )
    .join("");
  $("#scenarios").innerHTML = snapshot.scenarios
    .map((s) => {
      const r = snapshot.runs.find((r) => r.scenario_id === s.id);
      const missing = missed.some(
        (t) =>
          t.scenario_id === s.id &&
          (!r || Date.parse(t.scheduled_at) > Date.parse(r.scheduled_at)),
      );
      const due = snapshot.schedule
        .filter(
          (t) =>
            t.scenario_id === s.id && Date.parse(t.scheduled_at) > Date.now(),
        )
        .sort(
          (a, b) => Date.parse(a.scheduled_at) - Date.parse(b.scheduled_at),
        )[0];
      return `<article class="scenario"><div class="scenario-body"><div class="card-top"><span class="route-tag">${escapeHtml(s.tag)}</span>${badge(missing ? "overdue" : r ? outcome(r) : "waiting")}</div><h3>${escapeHtml(s.title)}</h3><p class="description">${escapeHtml(s.description)}</p><div class="route"><strong>${escapeHtml(s.route)}</strong>${due ? `Next: ${date(due.scheduled_at)}` : "Waiting for schedule update"}</div><div class="latest"><span>${missing ? "Prior recorded run" : "Latest run"}</span><span>${r ? date(r.scheduled_at) : "None recorded"}</span></div></div>${r ? `<details data-key="scenario-${escapeHtml(s.id)}"><summary>Inspect result<span class="sr-only"> for ${escapeHtml(s.title)}</span></summary>${evidence(r)}</details>` : '<p class="awaiting">No recorded result. This scenario has no score.</p>'}</article>`;
    })
    .join("");
  const filter = $("#outcome").value;
  const visible = [
    ...runs,
    ...missed.map((r) => ({ ...r, status: "overdue", evidence: {} })),
  ]
    .sort((a, b) => Date.parse(b.scheduled_at) - Date.parse(a.scheduled_at))
    .filter(
      (r) =>
        filter === "all" ||
        (filter === "error"
          ? ["error", "overdue", "stale"].includes(outcome(r))
          : outcome(r) === filter),
    );
  $("#history").innerHTML =
    visible
      .map((r) => {
        const s = snapshot.scenarios.find((s) => s.id === r.scenario_id);
        return `<details class="run" data-key="${escapeHtml(key(r))}"><summary><time datetime="${escapeHtml(r.scheduled_at)}">${date(r.scheduled_at)}</time><span class="run-title">${escapeHtml(s.title)}</span>${badge(outcome(r))}</summary>${evidence(r)}</details>`;
      })
      .join("") || '<p class="empty">No runs in this view yet.</p>';
  $("#shown").textContent =
    `${visible.length} shown · ${graded} graded · ${missed.length} expected runs missing`;
  document.querySelectorAll("details[data-key]").forEach((el) => {
    el.open = opened.has(el.dataset.key);
  });
}

function validate(data) {
  if (
    data.schema_version !== 1 ||
    data.environment !== expectedEnvironment ||
    !Number.isFinite(Date.parse(data.generated_at)) ||
    !Array.isArray(data.scenarios) ||
    data.scenarios.length !== 6 ||
    !Array.isArray(data.runs) ||
    !Array.isArray(data.schedule)
  )
    throw Error("Invalid snapshot");
  const ids = new Set(data.scenarios.map((s) => s.id));
  const states = new Set(["running", "passed", "failed", "error", "stale"]);
  if (
    ids.size !== 6 ||
    data.runs.some(
      (r) =>
        !ids.has(r.scenario_id) ||
        !states.has(r.status) ||
        !Number.isFinite(Date.parse(r.scheduled_at)),
    ) ||
    data.schedule.some(
      (r) =>
        !ids.has(r.scenario_id) || !Number.isFinite(Date.parse(r.scheduled_at)),
    )
  )
    throw Error("Invalid snapshot");
  for (const r of data.runs) {
    if (!r.evidence || typeof r.evidence !== "object")
      throw Error("Invalid evidence");
    const checks = r.evidence.checks || [],
      turns = r.evidence.turns || [];
    if (
      !Array.isArray(checks) ||
      checks.length > 3 ||
      !Array.isArray(turns) ||
      turns.length > 3 ||
      checks.some(
        (c) =>
          !Object.hasOwn(checkLabels, c.name) ||
          typeof c.passed !== "boolean" ||
          typeof c.reason !== "string",
      )
    )
      throw Error("Invalid evidence");
    if (
      ["passed", "failed"].includes(r.status) &&
      (new Set(checks.map((c) => c.name)).size !== 3 ||
        (r.status === "passed") !== checks.every((c) => c.passed))
    )
      throw Error("Invalid verdict");
    if (
      turns.some(
        (t) =>
          typeof t.user !== "string" ||
          typeof t.assistant !== "string" ||
          !Array.isArray(t.tools),
      )
    )
      throw Error("Invalid conversation");
  }
  return data;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const response = await fetch("/evals.json", {
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw Error("Snapshot unavailable");
    snapshot = validate(await response.json());
    failedRefresh = false;
  } catch {
    failedRefresh = true;
    if (!snapshot) {
      $("#environment").textContent =
        `${expectedEnvironment.toUpperCase()} · EVALUATION EXPLORER`;
      $("#freshness").textContent =
        "Results are not available yet. Retrying automatically.";
      $("#history").innerHTML =
        '<p class="empty">No verified snapshot could be loaded. No scores are shown.</p>';
    }
  } finally {
    refreshing = false;
    render();
  }
}
$("#outcome").addEventListener("change", render);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
setInterval(() => {
  if (!document.hidden) refresh();
}, 60000);
refresh();
