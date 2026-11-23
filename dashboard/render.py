from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from dashboard.report import RANGES, ZERO, Report

COST_TYPES = ("tokens", "session_usage", "web_search", "code_execution")
COLORS = ("#2563eb", "#d97706", "#059669", "#7c3aed", "#db2777", "#0891b2", "#65a30d")

STYLE = """
:root{color-scheme:light dark;--fg:#111827;--bg:#fff;--muted:#6b7280;--line:#d1d5db;--card:#f3f4f6}
@media (prefers-color-scheme:dark){:root{--fg:#f3f4f6;--bg:#111827;--muted:#9ca3af;--line:#374151;--card:#1f2937}}
*{box-sizing:border-box}
body{margin:0;padding:1rem;font:16px/1.45 system-ui,sans-serif;color:var(--fg);background:var(--bg)}
main{max-width:60rem;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 .25rem}
h2{font-size:1.15rem;margin:2rem 0 .5rem}
nav a{display:inline-block;padding:.4rem .8rem;margin:.25rem .25rem .25rem 0;border:1px solid var(--line);border-radius:.5rem;color:inherit;text-decoration:none}
nav a[aria-current=page]{background:var(--fg);color:var(--bg)}
.muted{color:var(--muted)}
.cards{display:flex;flex-wrap:wrap;gap:.75rem}
.card{flex:1 1 10rem;background:var(--card);border-radius:.5rem;padding:.75rem}
.card strong{display:block;font-size:1.6rem}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th,td{padding:.35rem .5rem;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
td.wrap{white-space:normal;word-break:break-all}
code{font-size:.8rem}
.bar{display:block;height:.5rem;background:#2563eb;border-radius:.25rem;min-width:1px}
svg{width:100%;height:auto;display:block}
.legend{list-style:none;padding:0;margin:.5rem 0;display:flex;flex-wrap:wrap;gap:.25rem 1rem}
.swatch{display:inline-block;width:.8rem;height:.8rem;margin-right:.3rem;border-radius:2px}
details summary{cursor:pointer;margin:.5rem 0}
"""


def dollars(cents: Decimal) -> str:
    value = (cents / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"${value:,.2f}"


def percent(fraction: Decimal | None) -> str:
    if fraction is None:
        return "n/a"
    return f"{(fraction * 100).quantize(Decimal('0.1'), ROUND_HALF_UP)}%"


def share(part: Decimal | int, total: Decimal | int) -> Decimal | None:
    return Decimal(part) / Decimal(total) if total else None


def _cell(key: str, text: str, tag: str = "td") -> str:
    return f'<{tag} data-k="{escape(key)}">{escape(text)}</{tag}>'


def _header(*names: str) -> str:
    return "<tr>" + "".join(f"<th>{escape(name)}</th>" for name in names) + "</tr>"


def _table(rows: list[str], head: str) -> str:
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def _bar(fraction: Decimal | None) -> str:
    width = float((fraction or ZERO) * 100)
    return f'<span class="bar" style="width:{width:.1f}%"></span>'


def _agent_shares(report: Report) -> str:
    rows: list[str] = []
    for agent in report.agents:
        cents = report.cents_by_agent.get(agent, ZERO)
        tokens = report.tokens_by_agent.get(agent, 0)
        cost_share = share(cents, report.total_cents)
        token_share = share(tokens, report.total_tokens)
        rows.append(
            "<tr>"
            f"<td>{escape(agent)}{_bar(cost_share)}</td>"
            + _cell(f"cost:{agent}", dollars(cents))
            + _cell(f"cost-share:{agent}", percent(cost_share))
            + _cell(f"tokens:{agent}", f"{tokens:,}")
            + _cell(f"token-share:{agent}", percent(token_share))
            + "</tr>"
        )
    return _table(rows, _header("Agent", "Cost", "Cost share", "Tokens", "Token share"))


def _daily_chart(report: Report) -> str:
    left, top, width, height, bottom = 56, 8, 640, 240, 24
    totals = [
        sum(
            (report.daily_cents.get((day, agent), ZERO) for agent in report.agents),
            ZERO,
        )
        for day in report.days
    ]
    peak = max([*totals, Decimal(1)])
    slot = (width - left) / len(report.days)
    plot = height - top - bottom
    parts: list[str] = []
    for index, day in enumerate(report.days):
        y = float(height - bottom)
        for position, agent in enumerate(report.agents):
            cents = report.daily_cents.get((day, agent), ZERO)
            if cents <= 0:
                continue
            bar = float(cents / peak) * plot
            y -= bar
            parts.append(
                f'<rect x="{left + index * slot + slot * 0.1:.2f}" y="{y:.2f}" '
                f'width="{slot * 0.8:.2f}" height="{bar:.2f}" '
                f'fill="{COLORS[position % len(COLORS)]}">'
                f"<title>{day} {escape(agent)} {dollars(cents)}</title></rect>"
            )
    first, last = report.days[0], report.days[-1]
    parts.append(
        f'<text x="{left}" y="{height - 6}" font-size="11" fill="currentColor">{first}</text>'
        f'<text x="{width}" y="{height - 6}" font-size="11" text-anchor="end" fill="currentColor">{last}</text>'
        f'<text x="{left - 4}" y="{top + 10}" font-size="11" text-anchor="end" fill="currentColor">{dollars(peak)}</text>'
        f'<text x="{left - 4}" y="{height - bottom}" font-size="11" text-anchor="end" fill="currentColor">$0</text>'
        f'<line x1="{left}" y1="{height - bottom}" x2="{width}" y2="{height - bottom}" stroke="currentColor" opacity=".4"/>'
    )
    legend = "".join(
        f'<li><span class="swatch" style="background:{COLORS[i % len(COLORS)]}"></span>{escape(agent)}</li>'
        for i, agent in enumerate(report.agents)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Daily cost stacked by agent">'
        + "".join(parts)
        + f'</svg><ul class="legend">{legend}</ul>'
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


def _details(report: Report, title: str, body: str) -> str:
    opened = " open" if len(report.days) <= 31 else ""
    return f"<details{opened}><summary>{escape(title)}</summary>{body}</details>"


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
        rows.append(f"<tr><td>{escape(agent)}</td>{''.join(cells)}</tr>")
    return _table(rows, _header("Agent", "Median", "p90", "Max"))


def _cost_types(report: Report) -> str:
    names = [*COST_TYPES, *sorted(set(report.cents_by_cost_type) - set(COST_TYPES))]
    rows: list[str] = []
    for name in names:
        cents = report.cents_by_cost_type.get(name, ZERO)
        rows.append(
            f"<tr><td>{escape(name)}{_bar(share(cents, report.total_cents))}</td>"
            + _cell(f"cost-type:{name}", dollars(cents))
            + _cell(
                f"cost-type-share:{name}", percent(share(cents, report.total_cents))
            )
            + "</tr>"
        )
    return _table(rows, _header("Cost type", "Cost", "Share"))


def _models(report: Report) -> str:
    rows: list[str] = []
    for model, tokens in report.tokens_by_model.items():
        fraction = share(tokens, report.total_tokens)
        rows.append(
            f"<tr><td>{escape(model)}{_bar(fraction)}</td>"
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
            f"<tr><td class='wrap'><code data-k=\"top:{rank}:session\">{escape(item.session_id)}</code></td>"
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
    cost_by_day = _by_day(
        report, "daily", report.daily_cents, lambda v: dollars(v or ZERO)
    )
    session_by_day = _by_day(report, "sessions", report.sessions, lambda v: str(v or 0))
    cache_by_day = _by_day(
        report, "cache", report.cache_efficiency, lambda v: percent(v)
    )
    sections = [
        f"<h1>Factory metrics</h1><p class='muted'>{RANGES[report.range_key]}: {report.first_day} to {report.last_day} (UTC). "
        f"Data refreshed at <time {_attr('refreshed-at')}>{escape(refreshed)}</time></p>",
        f"<nav aria-label='Time range'>{nav}</nav>",
        "<div class='cards'>"
        f"<div class='card'>Total cost<strong {_attr('total-cost')}>{dollars(report.total_cents)}</strong></div>"
        f"<div class='card'>Total tokens<strong {_attr('total-tokens')}>{report.total_tokens:,}</strong></div>"
        "</div>",
        "<h2>Cost and tokens by agent</h2>" + _agent_shares(report),
        "<h2>Daily cost by agent</h2>"
        + _daily_chart(report)
        + _details(report, "Daily cost table", cost_by_day),
        "<h2>Sessions per day</h2>"
        + _details(report, "Sessions per day table", session_by_day),
        "<h2>Cost per session</h2>" + _session_cost(report),
        "<h2>Cache efficiency</h2><p class='muted'>Cache reads divided by all input tokens.</p>"
        + _details(report, "Cache efficiency by day", cache_by_day),
        "<h2>Cost by type</h2>" + _cost_types(report),
        "<h2>Model mix by tokens</h2>" + _models(report),
        "<h2>10 most expensive sessions</h2>" + _top(report),
    ]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Factory metrics</title><style>{STYLE}</style></head>"
        f"<body><main>{''.join(sections)}</main></body></html>"
    )


def _attr(key: str) -> str:
    return f'data-k="{key}"'
