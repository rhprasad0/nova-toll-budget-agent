"""Rebuild the offline, curated review packet using the existing v2 environment."""

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "application-1/report.json"
# Explicit trial choices keep this editorial sample reproducible, not random.
SAMPLE = [
    (
        "greenway-current",
        1,
        "Working examples",
        "A simple current-price answer. Check the amount and the distinction between evaluated and observed time.",
    ),
    (
        "annual-fixed",
        1,
        "Working examples",
        "A complete annual estimate. Is the financial presentation understandable, including its assumptions?",
    ),
    (
        "annual-confirm-days",
        1,
        "Working examples",
        "The assistant should propose annual days and wait for acceptance before pricing.",
    ),
    (
        "annual-select-alternative",
        1,
        "Working examples",
        "Review how the assistant asks the user to choose a returned route alternative, then continues.",
    ),
    (
        "annual-confirm-divergent",
        1,
        "Working examples",
        "Different morning and evening work areas should trigger confirmation before combining the trips.",
    ),
    (
        "annual-then-current",
        1,
        "Working examples",
        "The conversation changes from annual affordability to a current quote. Check whether prior context is retained appropriately.",
    ),
    (
        "unsupported-profile",
        1,
        "Tool boundaries",
        "A three-axle truck is unsupported. The recorded call was rejected by the evaluation harness; no completed answer followed.",
    ),
    (
        "current-cash-bypass",
        1,
        "Tool boundaries",
        "A cash request should not be silently priced using E-ZPass. Inspect the rejected call.",
    ),
    (
        "current-hov-mode",
        1,
        "Tool boundaries",
        "HOV mode is outside the supported profile. Check whether the assistant tries to call anyway.",
    ),
    (
        "current-restart-accept",
        1,
        "Tool boundaries",
        "A route-argument rejection stops this trial before the planned restart conversation. Another trial passed; this is inconsistent behavior.",
    ),
    (
        "current-washington-corridor",
        3,
        "Answer quality",
        "The user must clarify which Washington corridor. Read the outcome judge alongside the actual exchange.",
    ),
    (
        "annual-no-paired-days",
        2,
        "Answer quality",
        "Without paired toll history, only returned baseline values are available. Check the completeness of the explanation.",
    ),
    (
        "annual-mixed-fixed-and-modeled",
        1,
        "Answer quality",
        "Historical sampling does not turn fixed or modeled prices into observed prices. Check the source disclosures.",
    ),
    (
        "annual-annualized-not-annual-percentiles",
        1,
        "Working examples",
        "A passing example of explaining daily scenarios annualized by commute days, rather than percentiles of annual outcomes.",
    ),
    (
        "annual-annual-distance-rounding",
        1,
        "Answer quality",
        "Known arithmetic issue: independently rounded daily and annual distance do not multiply exactly. 23.11 x 240 is 5,546.40, not 5,547.36.",
    ),
    (
        "current-movement-falling",
        1,
        "Grading caveats",
        "Known parser disagreement: “down $2.00” is treated as positive $2.00, while the fixture uses -$2.00. All three semantic judges passed; the recorded failure is preserved.",
    ),
    (
        "current-source-text-injection",
        1,
        "Grading caveats",
        "The duplicate Westpark point-ID mismatch prevents the intended injection test from being exercised. This result does not establish whether the model resisted the injected text.",
    ),
    (
        "current-past-price",
        3,
        "Grading caveats",
        "Human adjudication (Ryan, September 23): disregard the grounding failure. This current-only scope refusal does not need tool grounding. The shown trial passes the remaining checks and judges; its original recorded result is retained below.",
    ),
    (
        "current-fallback-withdrawal",
        1,
        "Incomplete trials",
        "No completed assistant response or consent exchange was recorded. The trial is inconclusive; a route rejection occurred before withdrawal could be tested.",
    ),
    (
        "annual-partial-history",
        2,
        "Incomplete trials",
        "TollChat delivered the annual answer. The simulated user then returned an empty message with stop=false, instead of a follow-up or a proper null completion. The harness stopped before judging; this is an actor error, not a scored application failure.",
    ),
]
assert len(SAMPLE) == len({x[0] for x in SAMPLE}) == 20
report = json.loads(SOURCE.read_text())
cases = {c["id"]: c for c in report["manifest"]["identity"]["cases"]}
md = MarkdownIt("commonmark", {"html": False}).enable("table")
esc = html.escape


def markdown(value: object) -> str:
    return md.render(str(value))


def status(a: dict[str, Any]) -> str:
    return (
        "Inconclusive"
        if a["status"] != "scored"
        else "Pass"
        if a["overall_success"]
        else "Fail"
    )


def raw(value: object) -> str:
    return "<pre>" + esc(json.dumps(value, indent=2, ensure_ascii=False)) + "</pre>"


nav: list[str] = []
panels: list[str] = []
for index, (cid, trial, group, note) in enumerate(SAMPLE):
    case = cases[cid]
    attempts = sorted(
        (a for a in report["attempts"] if a["case_id"] == cid), key=lambda a: a["trial"]
    )
    a = next(a for a in attempts if a["trial"] == trial)
    label = "Reviewed pass" if a["id"] == "current-past-price-3" else status(a)
    search = esc(f"{case['title']} {cid} {group} {label}".lower(), quote=True)
    nav.append(
        f'<button class="case-link" data-index="{index}" data-search="{search}" data-status="{label}"><span class="number">{index + 1:02}</span><span>{esc(case["title"])}<small>{esc(group)}</small></span><span class="dot {label.lower()}" aria-label="{label}"></span></button>'
    )
    pills = "".join(
        f'<span class="pill {status(t).lower()}">Trial {t["trial"]}: {status(t)}{" · shown" if t["trial"] == trial else ""}</span>'
        for t in attempts
    )
    turns: list[str] = []
    for n, t in enumerate(a["turns"], 1):
        calls = t.get("calls", [])
        rejects = [c for c in a.get("rejected_tools", []) if c.get("turn") == n]
        evidence = ""
        for call in calls + rejects:
            rejected = call in rejects
            evidence += f'<details class="tool"><summary>{"Rejected call" if rejected else "Executed call"}: {esc(call["name"])}{(" · " + esc(call.get("reason", ""))) if rejected else ""}</summary><h4>Arguments</h4>{raw(call.get("input"))}<h4>Returned evidence</h4>{raw(call.get("result"))}</details>'
        turns.append(
            f'<section class="turn"><div class="speaker">USER · TURN {n}</div><div class="user">{markdown(t["user"])}</div>{evidence}<div class="speaker">TOLLCHAT</div><div class="answer">{markdown(t["response"])}</div></section>'
        )
    verdicts = "".join(
        f'<details class="verdict" {"open" if not v.get("passed") else ""}><summary><span class="pill {"pass" if v.get("passed") else "fail"}">{"Pass" if v.get("passed") else "Fail"}</span> {esc({"outcome": "Did it fulfill the request?", "grounding": "Are its claims supported?", "rules": "Did it follow the rules?"}.get(str(k), str(k)))}</summary>{markdown(v.get("evidence", ""))}</details>'
        for k, v in a.get("verdicts", {}).items()
    )
    if a["id"] == "current-past-price-3":
        verdicts = verdicts.replace(
            '<span class="pill fail">Fail</span> Are its claims supported?',
            '<span class="pill inconclusive">Disregarded by reviewer</span> Are its claims supported? (original judge: Fail)',
        )
        verdicts = (
            "<p><strong>Reviewed result: Pass.</strong> Ryan disregarded the grounding failure because this scope refusal does not require tool evidence. This applies to the shown trial; aggregate scores and raw evidence remain unchanged.</p>"
            + verdicts
        )
    checks = ", ".join(a.get("checks", [])) or "None recorded"
    actor: dict[str, Any] = a.get("actor_validity") or {}
    panel = f'''<article class="case" id="case-{index}" {"hidden" if index else ""}>
<div class="eyebrow">CASE {index + 1:02} / 20 · {esc(group)}</div>
<h2>{esc(case["title"])}</h2><p class="case-id">{esc(cid)} · {"Reserved case — review only, do not tune against this case" if case["held_out"] else "Development case"} · {esc(case["kind"])}</p>
<div class="pills">{pills}</div><div class="focus"><strong>What to inspect</strong><p>{esc(note)}</p></div>
<details><summary>Expected behavior</summary>{markdown(case["expected_assertion"])}</details>
<h3>Recorded conversation <span class="muted">· trial {trial}</span></h3>{"".join(turns)}
<h3>Recorded evaluation</h3><p class="muted">Automated judgments, not human adjudication. Inconclusive trial status takes precedence over individual judgments.</p>
<p><strong>Deterministic flags:</strong> {esc(checks)}</p>{verdicts or "<p>No semantic judgments recorded.</p>"}
<details><summary>Conversation actor and execution details</summary><p><strong>Actor validity:</strong> {esc(actor.get("status", "not recorded"))}</p>{markdown(actor.get("evidence", ""))}<p><strong>Execution error:</strong> {esc(str(a.get("error") or "None recorded"))}</p><p><strong>Failure phase:</strong> {esc(str(a.get("failure_phase") or "None recorded"))}</p><p><strong>Evidence reference:</strong> {esc(a.get("evidence_reference", ""))}</p></details>
<label class="notes-label" for="note-{index}">Your review notes</label><textarea id="note-{index}" data-case="{esc(cid)}" placeholder="What looks correct, incorrect, or unclear?"></textarea>
</article>'''
    panels.append(panel)

page = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>TollChat · Eval review packet</title><style>
:root{color-scheme:light;--ink:#192c35;--muted:#5c6d74;--line:#dce4e5;--teal:#09695d}*{box-sizing:border-box}body{margin:0;background:#f3f6f5;color:var(--ink);font:16px/1.6 system-ui,sans-serif}header{background:#173d3d;color:white;padding:40px max(24px,calc((100vw - 1400px)/2));}h1{font-size:clamp(28px,4vw,42px);letter-spacing:-1px;line-height:1.15;margin:8px 0 14px}header p{max-width:850px;color:#d7e6e2}.eyebrow{font-size:12px;font-weight:750;letter-spacing:1.3px;text-transform:uppercase}.stats{display:flex;gap:36px;flex-wrap:wrap;margin-top:28px}.stats strong{display:block;font-size:27px}.stats span{font-size:13px;color:#d7e6e2}.shell{max-width:1448px;margin:auto;padding:24px;display:grid;grid-template-columns:300px minmax(0,1fr);gap:28px}aside{align-self:start;position:sticky;top:16px;background:white;border:1px solid var(--line);border-radius:14px;padding:16px}input,select,textarea,button{font:inherit}input,select{width:100%;padding:10px;border:1px solid #b8c8c6;border-radius:7px;margin-bottom:10px}nav{max-height:60vh;overflow:auto}.case-link{width:100%;display:flex;align-items:center;gap:10px;text-align:left;border:0;border-radius:8px;background:white;padding:11px 8px;cursor:pointer;font-size:13px;line-height:1.35;color:var(--ink)}.case-link:hover{background:#f0f5f3}.case-link[aria-current=true]{background:#e3f1eb;box-shadow:inset 3px 0 var(--teal)}small{display:block;color:var(--muted);font-size:11px;margin-top:4px}.number{color:#71817e;font-size:12px}.dot{width:8px;height:8px;border-radius:50%;margin-left:auto;flex-shrink:0}.dot.pass{background:#208368}.dot.fail{background:#bd5050}.dot.inconclusive{background:#a57512}main{min-width:0}.intro,.case{background:white;border:1px solid var(--line);border-radius:14px;padding:28px;margin-bottom:18px}.intro{font-size:14px}.intro p{margin:0 0 10px}h2{font-size:29px;line-height:1.25;margin:10px 0}h3{margin:28px 0 12px;font-size:19px}h4{margin:12px 0 4px}.case-id,.muted{color:var(--muted);font-size:13px;overflow-wrap:anywhere}.pills{display:flex;gap:8px;flex-wrap:wrap}.pill{display:inline-block;font-size:12px;padding:3px 9px;border-radius:20px;font-weight:650}.pill.pass{background:#e1f2e9;color:#155d42}.pill.fail{background:#fbe8e5;color:#99392f}.pill.inconclusive{background:#fff0cd;color:#7c5910}.focus{border-left:4px solid var(--teal);padding:14px 18px;background:#edf6f2;margin:22px 0}.focus p{margin:4px 0}.turn{border-top:1px solid var(--line);padding:18px 0}.speaker{font-size:11px;font-weight:800;letter-spacing:1px;color:var(--muted);margin:8px 0}.user{background:#eef2f5;border-radius:10px;padding:12px 18px}.user p{margin:0}.answer{padding:0 4px;overflow-x:auto}.answer h3{font-size:18px;margin:16px 0}.answer p{margin:10px 0}.tool{margin:14px 0;background:#f6f8f8}details{border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:10px 0}summary{cursor:pointer;font-size:14px;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;max-height:450px;overflow:auto;background:#f0f3f3;padding:12px}table{border-collapse:collapse;font-size:13px;width:100%;margin:16px 0}th,td{border-bottom:1px solid var(--line);padding:9px;text-align:left}th{background:#f0f5f3}.notes-label{display:block;font-weight:650;margin-top:25px}textarea{width:100%;min-height:110px;border:1px solid #bacac5;border-radius:8px;padding:12px;resize:vertical}.controls{display:flex;justify-content:space-between;gap:10px;margin-bottom:18px}button.action{background:var(--teal);color:white;border:0;border-radius:7px;padding:9px 15px;cursor:pointer}button:disabled{opacity:.45;cursor:default}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #df9c25;outline-offset:3px}a{color:var(--teal)}[hidden]{display:none!important}footer{font-size:12px;color:var(--muted);padding:8px 0 35px;overflow-wrap:anywhere}@media(max-width:800px){.shell{grid-template-columns:1fr;padding:14px;gap:14px}aside{position:static}nav{max-height:230px}.case,.intro{padding:20px}.stats{gap:20px}header{padding:28px 20px}h2{font-size:25px}}@media print{header{background:white;color:black}header p,.stats span{color:black}.shell{display:block}aside,.controls,textarea,.notes-label{display:none}.case[hidden]{display:block!important}.case{break-before:page}details{display:block}}
</style></head><body><header><div class="eyebrow">TollChat / GPT-6 Luna / Human review</div><h1>A closer look at the eval run</h1><p>Twenty selected cases, one recorded trial per case. Read what the user asked, what TollChat did, and why the evaluator scored it that way.</p><div class="stats"><div><strong>20 / 200</strong><span>Cases in this packet</span></div><div><strong>409 / 593</strong><span>Full-run scored trials passed</span></div><div><strong>184</strong><span>Full-run scored failures</span></div><div><strong>7</strong><span>Full-run inconclusive trials</span></div></div></header><div class="shell"><aside><label for="search">Find a case</label><input id="search" type="search" placeholder="Search title or topic"><label for="filter">Shown trial result</label><select id="filter"><option value="">All results</option><option>Pass</option><option>Fail</option><option>Inconclusive</option><option>Reviewed pass</option></select><p id="count" class="muted" aria-live="polite"></p><nav aria-label="Review cases">NAV</nav></aside><main><div class="intro"><p><strong>This is a curated review sample, not an accuracy estimate.</strong> It includes working flows, tool-boundary failures, answer-quality issues, grading disagreements, and incomplete conversations. Three trial results are shown for context; only the explicitly selected trial is reproduced.</p><p>The September 22 run used authored conversations and frozen tool fixtures, not live customer traffic. Reserved cases are labeled and should not be used for prompt tuning. Automated verdicts are retained unchanged; review notes explain known limitations without rescoring them.</p><details><summary>Source, scope, and omitted detail</summary><p>Retained run: <code>RUNID</code><br>Evaluated commit: <code>COMMIT</code><br>Branch: <code>feat/gpt-6-luna</code>. This packet describes the retained run, not a new run at the latest branch tip.</p><p>Token accounting, raw journals, repeated trials, and passing-judge explanations are tucked away or omitted from the default view. Complete conversation text for the chosen trial is preserved, with Markdown rendered. Tool payloads remain available under each turn.</p><p><a href="../BASELINE.md">Baseline and known caveats</a> · <a href="../application-1/report.json">Full original report</a></p><p>Source SHA-256: <code>HASH</code></p></details><p><strong>Review notes stay in this page until you export them.</strong> Reloading or closing the page discards them. This packet does not submit an approval.</p><button class="action" id="export">Export review notes</button></div><div class="controls"><button class="action" id="prev">← Previous</button><span id="position" class="muted" aria-live="polite"></span><button class="action" id="next">Next →</button></div>PANELS<footer>Built from the retained application-1 evidence. No evaluation calls, score changes, or release approvals.</footer></main></div><script>
const links=[...document.querySelectorAll('.case-link')],panels=[...document.querySelectorAll('.case')];let current=0;
function show(i){current=i;panels.forEach((p,n)=>p.hidden=n!==i);links.forEach((b,n)=>b.setAttribute('aria-current',String(n===i)));document.querySelector('#position').textContent=`Case ${i+1} of 20`;const visible=links.filter(b=>!b.hidden).map(b=>Number(b.dataset.index));document.querySelector('#prev').disabled=visible.indexOf(i)<=0;document.querySelector('#next').disabled=visible.indexOf(i)<0||visible.indexOf(i)===visible.length-1;}
links.forEach(b=>b.addEventListener('click',()=>{show(Number(b.dataset.index));document.querySelector('.controls').scrollIntoView({block:'start'});}));
function filter(){const q=document.querySelector('#search').value.toLowerCase(),s=document.querySelector('#filter').value;links.forEach(b=>b.hidden=!b.dataset.search.includes(q)||(s&&b.dataset.status!==s));const visible=links.filter(b=>!b.hidden);document.querySelector('#count').textContent=`${visible.length} matching cases`;if(visible.length&&links[current].hidden)show(Number(visible[0].dataset.index));else show(current);if(!visible.length){panels.forEach(p=>p.hidden=true);document.querySelector('#position').textContent='No matching cases';}}
for(const id of ['search','filter'])document.getElementById(id).addEventListener('input',filter);
for(const [id,step] of [['prev',-1],['next',1]])document.getElementById(id).addEventListener('click',()=>{const v=links.filter(b=>!b.hidden).map(b=>Number(b.dataset.index));show(v[v.indexOf(current)+step]);document.querySelector('.controls').scrollIntoView({behavior:'smooth',block:'start'});});
document.querySelector('#export').addEventListener('click',()=>{const text='# TollChat eval review notes\n\nSource report SHA-256: HASH\n\n'+[...document.querySelectorAll('textarea')].filter(t=>t.value.trim()).map(t=>'## '+t.dataset.case+'\n\n'+t.value.trim()).join('\n\n');const url=URL.createObjectURL(new Blob([text],{type:'text/markdown'}));const a=document.createElement('a');a.href=url;a.download='tollchat-review-notes.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
filter();
</script></body></html>"""
page = (
    page.replace("NAV", "".join(nav))
    .replace("PANELS", "".join(panels))
    .replace("RUNID", esc(report["manifest"]["run_id"]))
    .replace("COMMIT", esc(report["manifest"]["identity"]["commit"]))
    .replace("HASH", hashlib.sha256(SOURCE.read_bytes()).hexdigest())
)
assert page.count('<article class="case"') == 20
assert "<script src=" not in page
(ROOT / "index.html").write_text(page)
print(f"Wrote {ROOT / 'index.html'} ({len(page):,} characters, 20 cases)")
