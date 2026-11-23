import json
import math
from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from dashboard.agents import OTHER
from dashboard.report import RANGES, ZERO, Report

COST_TYPES = ("tokens", "session_usage", "web_search", "code_execution")
SLOTS = 8

STYLE = """
:root{color-scheme:light;
--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;--s-other:#a8a69e}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
--plane:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c;--s7:#9085e9;--s8:#e66767;--s-other:#6b6a64}}
:root[data-theme="dark"]{color-scheme:dark;
--plane:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c;--s7:#9085e9;--s8:#e66767;--s-other:#6b6a64}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 48px;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--plane)}
main{max-width:64rem;margin:0 auto}
header{display:flex;flex-wrap:wrap;align-items:end;justify-content:space-between;gap:12px;margin-bottom:20px}
h1{font-size:1.6rem;line-height:1.2;margin:0}
.lede{margin:4px 0 0;color:var(--ink-2)}
h2{font-size:1rem;margin:0 0 2px}
.sub{margin:0 0 14px;color:var(--muted);font-size:.85rem}
.muted{color:var(--muted)}
nav{display:inline-flex;padding:3px;border-radius:10px;background:var(--surface);box-shadow:0 0 0 1px var(--ring)}
nav a{padding:6px 12px;border-radius:7px;color:var(--ink-2);text-decoration:none;font-size:.9rem}
nav a:hover{background:var(--plane)}
nav a[aria-current=page]{background:var(--ink);color:var(--surface);font-weight:600}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,28rem),1fr))}
.panel{background:var(--surface);border-radius:14px;padding:18px;box-shadow:0 0 0 1px var(--ring);min-width:0}
.wide{grid-column:1/-1}
.hero{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px}
.hero .panel{flex:1 1 9rem}
.hero .lead{flex:1.6 1 14rem}
.hero .panel span{display:block;color:var(--ink-2);font-size:.85rem}
.hero .panel strong{display:block;font-size:1.7rem;font-weight:600;line-height:1.25;margin-top:4px}
.hero .lead strong{font-size:3.25rem;letter-spacing:-.02em}
.seg{display:flex;gap:2px;height:28px;margin:4px 0 10px}
.seg span{border-radius:4px;color:#fff;font-size:.78rem;font-weight:600;line-height:28px;padding-left:8px;white-space:nowrap;overflow:visible;min-width:2px}
.seg span.dark{color:#0b0b0b}
.legend{list-style:none;padding:0;margin:8px 0 0;display:flex;flex-wrap:wrap;gap:4px 16px;font-size:.85rem;color:var(--ink-2)}
.key{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.lkey{display:inline-block;width:14px;height:2px;border-radius:1px;margin-right:6px;vertical-align:3px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem;font-variant-numeric:tabular-nums}
th{font-weight:500;color:var(--muted);font-size:.78rem;text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid)}
td{padding:7px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:0}
th:first-child,td:first-child{text-align:left}
code{font-size:.78rem;color:var(--ink-2)}
.meter{display:block;height:4px;border-radius:2px;background:var(--grid);margin-top:5px}
.meter i{display:block;height:4px;border-radius:2px;background:var(--s1);min-width:2px}
.chart{overflow-x:auto;margin:0 -4px;padding:0 4px}
svg{width:100%;min-width:560px;height:auto;display:block;overflow:visible}
svg text{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.gridline{stroke:var(--grid);stroke-width:1}
.baseline{stroke:var(--axis);stroke-width:1}
.hit{fill:transparent;cursor:crosshair;outline:none}
.hit:hover,.hit:focus-visible{fill:var(--ink);fill-opacity:.05}
details{margin-top:12px}
details summary{cursor:pointer;color:var(--ink-2);font-size:.85rem}
#tip{position:fixed;pointer-events:none;z-index:9;background:var(--surface);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:.8rem;box-shadow:0 0 0 1px var(--ring),0 6px 20px rgba(0,0,0,.15);display:none;min-width:9rem}
#tip b{display:block;color:var(--muted);font-weight:500;margin-bottom:4px}
#tip div{display:flex;align-items:center;gap:6px;justify-content:space-between}
#tip div span{color:var(--ink-2)}
#tip div strong{font-variant-numeric:tabular-nums}
@media (forced-colors:active){.seg span,.key,.lkey{forced-color-adjust:none}}
"""

SCRIPT = """
(()=>{for(const c of document.querySelectorAll('.chart'))c.scrollLeft=c.scrollWidth;
const tip=document.getElementById('tip');if(!tip)return;
const show=(el,x,y)=>{const rows=JSON.parse(el.dataset.tip);tip.replaceChildren();
const h=document.createElement('b');h.textContent=rows[0];tip.append(h);
for(const [name,color,value] of rows.slice(1)){const r=document.createElement('div');
const l=document.createElement('span');const k=document.createElement('i');k.className='lkey';k.style.background=color;
l.append(k,document.createTextNode(name));const v=document.createElement('strong');v.textContent=value;r.append(l,v);tip.append(r)}
tip.style.display='block';const w=tip.offsetWidth,ht=tip.offsetHeight;
tip.style.left=Math.min(innerWidth-w-8,Math.max(8,x+14))+'px';tip.style.top=Math.max(8,y-ht-12)+'px'};
const hide=()=>{tip.style.display='none'};
for(const el of document.querySelectorAll('[data-tip]')){
el.addEventListener('pointermove',e=>show(el,e.clientX,e.clientY));el.addEventListener('pointerleave',hide);
el.addEventListener('focus',()=>{const b=el.getBoundingClientRect();show(el,b.right,b.top)});el.addEventListener('blur',hide)}})();
"""


def color(report: Report, agent: str) -> str:
    if agent == OTHER:
        return "var(--s-other)"
    return f"var(--s{report.agents.index(agent) % SLOTS + 1})"


def dark_label(report: Report, agent: str) -> bool:
    return agent != OTHER and report.agents.index(agent) % SLOTS == 3


def dollars(cents: Decimal) -> str:
    value = (cents / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"${value:,.2f}"


def compact(value: float) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            return f"{value / size:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{value:,.0f}"


def percent(fraction: Decimal | None) -> str:
    if fraction is None:
        return "n/a"
    return f"{(fraction * 100).quantize(Decimal('0.1'), ROUND_HALF_UP)}%"


def share(part: Decimal | int, total: Decimal | int) -> Decimal | None:
    return Decimal(part) / Decimal(total) if total else None


def nice_ticks(peak: float, count: int = 4) -> list[float]:
    if peak <= 0:
        return [0.0, 1.0]
    raw = peak / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    return [step * i for i in range(math.ceil(peak / step - 1e-9) + 1)]


def _cell(key: str, text: str, tag: str = "td") -> str:
    return f'<{tag} data-k="{escape(key)}">{escape(text)}</{tag}>'


def _header(*names: str) -> str:
    return "<tr>" + "".join(f"<th>{escape(name)}</th>" for name in names) + "</tr>"


def _table(rows: list[str], head: str) -> str:
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def _meter(fraction: Decimal | None) -> str:
    width = float((fraction or ZERO) * 100)
    return f'<span class="meter"><i style="width:{width:.1f}%"></i></span>'


def _key(report: Report, agent: str, line: bool = False) -> str:
    return f'<i class="{"lkey" if line else "key"}" style="background:{color(report, agent)}"></i>'


def _legend(report: Report, agents: list[str], line: bool = False) -> str:
    items = "".join(
        f"<li>{_key(report, agent, line)}{escape(agent)}</li>" for agent in agents
    )
    return f'<ul class="legend">{items}</ul>'


def _tip(rows: list[object]) -> str:
    return escape(json.dumps(rows), quote=True)


def _panel(title: str, sub: str, body: str, wide: bool = False) -> str:
    cls = "panel wide" if wide else "panel"
    note = f"<p class='sub'>{escape(sub)}</p>" if sub else "<p class='sub'></p>"
    return f"<section class='{cls}'><h2>{escape(title)}</h2>{note}{body}</section>"


def _share_bar(report: Report) -> str:
    total = report.total_cents
    if not total:
        return "<p class='muted'>No cost yet.</p>"
    blocks: list[str] = []
    for agent in report.agents:
        cents = report.cents_by_agent.get(agent, ZERO)
        if cents <= 0:
            continue
        fraction = cents / total
        label = percent(fraction) if fraction >= Decimal("0.08") else ""
        cls = ' class="dark"' if dark_label(report, agent) else ""
        blocks.append(
            f'<span{cls} style="flex:{float(fraction):.4f};background:{color(report, agent)}" '
            f'title="{escape(agent)}: {dollars(cents)} ({percent(fraction)})">{label}</span>'
        )
    present = [a for a in report.agents if report.cents_by_agent.get(a, ZERO) > 0]
    return (
        f'<div class="seg" role="img" aria-label="Cost share by agent">{"".join(blocks)}</div>'
        + _legend(report, present)
    )


def _agent_shares(report: Report) -> str:
    rows: list[str] = []
    for agent in report.agents:
        cents = report.cents_by_agent.get(agent, ZERO)
        tokens = report.tokens_by_agent.get(agent, 0)
        cost_share = share(cents, report.total_cents)
        token_share = share(tokens, report.total_tokens)
        rows.append(
            "<tr>"
            f"<td>{_key(report, agent)}{escape(agent)}</td>"
            + _cell(f"cost:{agent}", dollars(cents))
            + _cell(f"cost-share:{agent}", percent(cost_share))
            + _cell(f"tokens:{agent}", f"{tokens:,}")
            + _cell(f"token-share:{agent}", percent(token_share))
            + "</tr>"
        )
    return _table(rows, _header("Agent", "Cost", "Cost share", "Tokens", "Token share"))


def _frame(
    ticks: list[float], tick_label: Callable[[float], str], days: list[date]
) -> tuple[list[str], Callable[[float], float], float, float]:
    left, top, right, height, bottom = 48, 8, 680, 220, 22
    plot = height - top - bottom
    peak = ticks[-1]

    def y(value: float) -> float:
        return height - bottom - (value / peak) * plot

    parts: list[str] = []
    for tick in ticks:
        cls = "baseline" if tick == 0 else "gridline"
        parts.append(
            f'<line class="{cls}" x1="{left}" y1="{y(tick):.1f}" x2="{right}" y2="{y(tick):.1f}"/>'
            f'<text x="{left - 8}" y="{y(tick) + 4:.1f}" text-anchor="end">{escape(tick_label(tick))}</text>'
        )
    slot = (right - left) / len(days)
    stride = max(1, math.ceil(len(days) / 6))
    for index in range(0, len(days), stride):
        x = left + (index + 0.5) * slot
        parts.append(
            f'<text x="{x:.1f}" y="{height - 4}" text-anchor="middle">{days[index]:%b %-d}</text>'
        )
    return parts, y, left, slot


def _svg(label: str, parts: list[str]) -> str:
    return (
        f'<div class="chart"><svg viewBox="0 0 680 220" role="img" aria-label="{escape(label)}">'
        + "".join(parts)
        + "</svg></div>"
    )


def _columns(
    report: Report,
    label: str,
    values: Mapping[tuple[date, str], Decimal | int],
    fmt: Callable[[Decimal | int], str],
    tick_label: Callable[[float], str],
) -> str:
    totals = [
        sum((values.get((day, a), 0) for a in report.agents), 0) for day in report.days
    ]
    ticks = nice_ticks(float(max([*totals, 0])))
    parts, y, left, slot = _frame(ticks, tick_label, report.days)
    width = min(24.0, slot * 0.7)
    for index, day in enumerate(report.days):
        x = left + index * slot + (slot - width) / 2
        stack = [
            (a, values.get((day, a), 0))
            for a in report.agents
            if values.get((day, a), 0) > 0
        ]
        base = 0.0
        for position, (agent, value) in enumerate(stack):
            y0, y1 = y(base), y(base + float(value))
            base += float(value)
            gap = 2 if position else 0
            h = max(y0 - y1 - gap, 0.5)
            top_y = y1
            if position == len(stack) - 1:
                r = min(4.0, h, width / 2)
                parts.append(
                    f'<path d="M{x:.1f},{top_y + h:.1f}V{top_y + r:.1f}'
                    f"Q{x:.1f},{top_y:.1f} {x + r:.1f},{top_y:.1f}H{x + width - r:.1f}"
                    f'Q{x + width:.1f},{top_y:.1f} {x + width:.1f},{top_y + r:.1f}V{top_y + h:.1f}Z" '
                    f'fill="{color(report, agent)}"/>'
                )
            else:
                parts.append(
                    f'<rect x="{x:.1f}" y="{top_y:.1f}" width="{width:.1f}" height="{h:.1f}" '
                    f'fill="{color(report, agent)}"/>'
                )
        rows: list[object] = [f"{day:%a %b %-d}"]
        rows += [[a, color(report, a), fmt(v)] for a, v in reversed(stack)]
        if len(stack) > 1:
            rows.append(["total", "transparent", fmt(sum((v for _, v in stack), 0))])
        if stack:
            parts.append(
                f'<rect class="hit" tabindex="0" x="{left + index * slot:.1f}" y="0" '
                f'width="{slot:.1f}" height="198" data-tip="{_tip(rows)}" '
                f'aria-label="{escape(str(day))}"/>'
            )
    present = [
        a for a in report.agents if any(values.get((d, a), 0) for d in report.days)
    ]
    return _svg(label, parts) + _legend(report, present)


def _cache_lines(report: Report) -> str:
    parts, y, left, slot = _frame(
        [0, 0.25, 0.5, 0.75, 1.0], lambda t: f"{t:.0%}", report.days
    )
    present = [
        a
        for a in report.agents
        if any(report.cache_efficiency.get((d, a)) is not None for d in report.days)
    ]
    for agent in present:
        runs: list[list[tuple[float, float]]] = [[]]
        for index, day in enumerate(report.days):
            value = report.cache_efficiency.get((day, agent))
            if value is None:
                if runs[-1]:
                    runs.append([])
                continue
            runs[-1].append((left + (index + 0.5) * slot, y(float(value))))
        for run in runs:
            if len(run) > 1:
                points = " ".join(f"{px:.1f},{py:.1f}" for px, py in run)
                parts.append(
                    f'<polyline points="{points}" fill="none" stroke="{color(report, agent)}" '
                    f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
                )
            for px, py in run:
                parts.append(
                    f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color(report, agent)}" '
                    f'stroke="var(--surface)" stroke-width="2"/>'
                )
    for index, day in enumerate(report.days):
        rows: list[object] = [f"{day:%a %b %-d}"]
        rows += [
            [a, color(report, a), percent(report.cache_efficiency.get((day, a)))]
            for a in present
            if report.cache_efficiency.get((day, a)) is not None
        ]
        if len(rows) > 1:
            parts.append(
                f'<rect class="hit" tabindex="0" x="{left + index * slot:.1f}" y="0" '
                f'width="{slot:.1f}" height="198" data-tip="{_tip(rows)}" '
                f'aria-label="{escape(str(day))}"/>'
            )
    return _svg("Cache efficiency by agent and day", parts) + _legend(
        report, present, line=True
    )


def _by_day[T](
    report: Report,
    prefix: str,
    values: Mapping[tuple[date, str], T],
    fmt: Callable[[T | None], str],
) -> str:
    rows = [
        "<tr>"
        + f"<td>{day}</td>"
        + "".join(
            _cell(f"{prefix}:{day}:{agent}", fmt(values.get((day, agent))))
            for agent in report.agents
        )
        + "</tr>"
        for day in reversed(report.days)
    ]
    return _table(rows, _header("Day", *report.agents))


def _details(title: str, body: str) -> str:
    return f"<details><summary>{escape(title)}</summary>{body}</details>"


def _session_cost(report: Report) -> str:
    rows: list[str] = []
    for agent in report.agents:
        stats = report.session_stats.get(agent)
        cells = [
            _cell(
                f"session-cost:{agent}:{name}",
                dollars(getattr(stats, attr)) if stats else "n/a",
            )
            for name, attr in (("median", "median"), ("p90", "p90"), ("max", "maximum"))
        ]
        rows.append(
            f"<tr><td>{_key(report, agent)}{escape(agent)}</td>{''.join(cells)}</tr>"
        )
    return _table(rows, _header("Agent", "Median", "p90", "Max"))


def _cost_types(report: Report) -> str:
    names = [*COST_TYPES, *sorted(set(report.cents_by_cost_type) - set(COST_TYPES))]
    rows: list[str] = []
    for name in names:
        cents = report.cents_by_cost_type.get(name, ZERO)
        fraction = share(cents, report.total_cents)
        rows.append(
            f"<tr><td>{escape(name.replace('_', ' '))}{_meter(fraction)}</td>"
            + _cell(f"cost-type:{name}", dollars(cents))
            + _cell(f"cost-type-share:{name}", percent(fraction))
            + "</tr>"
        )
    return _table(rows, _header("Cost type", "Cost", "Share"))


def _models(report: Report) -> str:
    rows: list[str] = []
    for model, tokens in report.tokens_by_model.items():
        fraction = share(tokens, report.total_tokens)
        rows.append(
            f"<tr><td>{escape(model)}{_meter(fraction)}</td>"
            + _cell(f"model:{model}", f"{tokens:,}")
            + _cell(f"model-share:{model}", percent(fraction))
            + "</tr>"
        )
    return (
        _table(rows, _header("Model", "Tokens", "Share"))
        if rows
        else "<p class='muted'>No usage yet.</p>"
    )


def _top(report: Report) -> str:
    rows: list[str] = []
    for rank, item in enumerate(report.top_sessions, start=1):
        rows.append(
            f'<tr><td><code data-k="top:{rank}:session">{escape(item.session_id)}</code></td>'
            + _cell(f"top:{rank}:agent", item.agent)
            + _cell(f"top:{rank}:date", str(item.day))
            + _cell(f"top:{rank}:tokens", f"{item.tokens:,}")
            + _cell(f"top:{rank}:cost", dollars(item.cents))
            + "</tr>"
        )
    return (
        _table(rows, _header("Session", "Agent", "Date", "Tokens", "Cost"))
        if rows
        else "<p class='muted'>No sessions yet.</p>"
    )


def render(report: Report) -> str:
    nav = "".join(
        f'<a href="?range={key}"{' aria-current="page"' if key == report.range_key else ""}>{label}</a>'
        for key, label in RANGES.items()
    )
    refreshed = (
        f"{report.refreshed_at:%Y-%m-%d %H:%M} UTC" if report.refreshed_at else "never"
    )
    total_sessions = sum(report.sessions.values())
    active_days = len(
        {day for (day, _), cents in report.daily_cents.items() if cents > 0}
    )
    per_session = (
        dollars(report.total_cents / total_sessions) if total_sessions else "n/a"
    )
    cost_by_day = _by_day(
        report, "daily", report.daily_cents, lambda v: dollars(v or ZERO)
    )
    session_by_day = _by_day(report, "sessions", report.sessions, lambda v: str(v or 0))
    cache_by_day = _by_day(report, "cache", report.cache_efficiency, percent)
    header = (
        "<header><div><h1>Factory metrics</h1>"
        "<p class='lede'>What the TollChat factory's Claude agents cost to run, from Anthropic usage and cost data.</p>"
        f"<p class='sub'>{RANGES[report.range_key]}: {report.first_day} to {report.last_day} (UTC) · "
        f"data refreshed <time {_attr('refreshed-at')}>{escape(refreshed)}</time></p></div>"
        f"<nav aria-label='Time range'>{nav}</nav></header>"
    )
    hero = (
        "<div class='hero'>"
        f"<div class='panel lead'><span>Total cost</span><strong {_attr('total-cost')}>{dollars(report.total_cents)}</strong></div>"
        f"<div class='panel'><span>Total tokens</span><strong {_attr('total-tokens')}>{report.total_tokens:,}</strong></div>"
        f"<div class='panel'><span>Sessions</span><strong>{total_sessions:,}</strong></div>"
        f"<div class='panel'><span>Cost per session</span><strong>{per_session}</strong></div>"
        f"<div class='panel'><span>Active days</span><strong>{active_days}</strong></div>"
        "</div>"
    )
    panels = [
        _panel(
            "Cost by agent",
            "Share of spend, then cost and tokens for each agent.",
            _share_bar(report) + _agent_shares(report),
            wide=True,
        ),
        _panel(
            "Daily cost",
            "Stacked by agent. Hover or focus a day for the breakdown.",
            _columns(
                report,
                "Daily cost stacked by agent",
                report.daily_cents,
                lambda v: dollars(Decimal(v)),
                lambda t: f"${t / 100:,.0f}" if t % 100 == 0 else f"${t / 100:,.2f}",
            )
            + _details("Daily cost table", cost_by_day),
            wide=True,
        ),
        _panel(
            "Sessions per day",
            "Managed Agents sessions started, by agent.",
            _columns(
                report,
                "Sessions per day by agent",
                report.sessions,
                lambda v: f"{v:,}",
                compact,
            )
            + _details("Sessions per day table", session_by_day),
            wide=True,
        ),
        _panel(
            "Cache efficiency",
            "Cache reads divided by all input tokens.",
            _cache_lines(report) + _details("Cache efficiency by day", cache_by_day),
            wide=True,
        ),
        _panel(
            "Cost per session",
            "Median, p90 and max session cost.",
            _session_cost(report),
            wide=True,
        ),
        _panel(
            "Cost by type",
            "Tokens, session runtime, web search and code execution.",
            _cost_types(report),
        ),
        _panel("Model mix", "Share of tokens by model.", _models(report)),
        _panel(
            "Most expensive sessions",
            "The 10 costliest sessions in range.",
            _top(report),
            wide=True,
        ),
    ]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Factory metrics</title><style>{STYLE}</style></head>"
        f"<body><main>{header}{hero}<div class='grid'>{''.join(panels)}</div></main>"
        f"<div id='tip' role='tooltip'></div><script>{SCRIPT}</script></body></html>"
    )


def _attr(key: str) -> str:
    return f'data-k="{key}"'
