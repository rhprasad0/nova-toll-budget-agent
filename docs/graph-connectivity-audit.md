# NOVA Toll Graph — Connectivity & Parallel-Edge Audit

**Generated:** 2026-07-25 · **Source of truth:** `db/graph.sql` (graph schema
v1.1.1) · **Spec:** `docs/toll-graph-spec.md` §6–7

> **Superseded snapshot.** This audited graph schema v1.1.1. v1.2.0 split the
> Springfield node by arrival road (61 nodes / 343 edges / 6 connectors);
> counts below are the pre-split figures. See `docs/toll-graph-spec.md` §1
> and `tests/test_expresslanes_topology.py`.

## 1. Summary

This report independently and exhaustively verifies two claims
`docs/toll-graph-spec.md` makes about the toll graph:

- §6: "BFS spot-checks confirm the graph is actually connected end-to-end."
  The existing spot-checks in `tests/test_graph.py` only probe 4 specific
  node pairs — this report checks all of them.
- §7: parallel public edges exist — "e.g. `pub:westpark → pub:i495-n`
  carries two rows." The spec doesn't claim that's the only one.

**Method.** Parsed `db/graph.sql` with the exact regexes
`tests/test_graph.py` already uses (`NODES`/`EDGES`/`ALIASES`, imported
directly — no re-derivation, no DB connection needed). Built the raw 60-node
graph and the public 46-node graph (reproducing `public_graph_edge`'s own
`feed IS NOT NULL` + alias-join definition), then ran weak-connectivity,
strong-connectivity (SCC), and full parallel-edge-group checks against both.

**Headline verdict:** **Both graphs are connected** — one weak component
each, no islands. The public graph's directed shape is a clean hub-and-spoke:
a 25-node strongly-connected core, plus 21 nodes that are pure sources, pure
sinks, or (6 of them, all I-66 ITB) directed pass-throughs — every one of
these is explained by known feed structure, not a data gap. Parallel edges
are more widespread than the spec's one example suggests: **18** distinct
public `(from, to)` pairs carry more than one priced product, not 1.

## 2. Connectivity

### 2a. Raw graph (60 nodes / 342 edges)

| Check | Result |
|---|---|
| Weak components | **1** (all 60 nodes) |
| Fully isolated nodes (no in, no out) | 0 |
| Entry-only nodes (out-edges, no in-edges) | 12 |
| Exit-only nodes (in-edges, no out-edges) | 13 |

Entry-only: `i495x:i495-hov`, `i495x:i495-near-md`, `i95x:alban`,
`i95x:cardinal`, `i95x:dale-blvd`, `i95x:dc-pentagon-washington-blvd`,
`i95x:i95-s-ft-belvoir`, `i95x:lorton`, `i95x:pentagon`, `i95x:rt17-95-nb`,
`i95x:telegraph-rd`, `i95x:turkeycock`.

Exit-only: `i495x:i495-n`, `i495x:jones-branch-rt267`,
`i495x:westpark-c`, `i95x:dumfries`, `i95x:i395-95`,
`i95x:i95-s-near-backlick-rd`, `i95x:i95-s-near-dale-blvd`,
`i95x:joplin-rd`, `i95x:newington`, `i95x:rt17-95-sb`, `i95x:russell-rd`,
`i95x:washington-blvd-pentagon`, `i95x:washington-dc`.

This asymmetry is expected — I-95/395/495 Express Lanes are reversible, so
many raw nodes only carry a priced trip in one direction at a time in the
feed. Not a defect.

### 2b. Public graph (46 nodes / 337 priced edges)

| Check | Result |
|---|---|
| Weak components | **1** (all 46 nodes — no islands) |
| Fully isolated nodes | 0 |
| Strongly-connected core | **1 SCC, 25 nodes** |
| Pure entry-only nodes | 8 |
| Pure exit-only nodes | 7 |
| Directed pass-through nodes (in edges + out edges, but not round-trippable) | 6 |

`8 + 7 + 6 + 25 = 46` — every node accounted for.

**Core (25, mutually reachable):** Braddock Rd, Dale Blvd, Fairfax County
Pkwy (286), Franconia Rd (644), Franconia-Springfield Pkwy (289), Gallows
Rd, Garrisonville Rd (610), Gordon Blvd (123), I-395 N, I-66 / Beltway
Interchange, Jones Branch Dr, Lee Hwy, Old Courthouse Rd, Opitz, Prince
William Pkwy (294), Quantico, Route 7, Rt 17 (Stafford), Rt 267 (Dulles
Access), Seminary Rd, Shirlington Circle, Springfield Interchange, US 1,
Washington Blvd / Pentagon, Westpark Dr.

**Entry-only (8):** Alban, Cardinal, I-495 near MD, I-95 S / Ft Belvoir,
Lorton, Pentagon, Telegraph Rd, Turkeycock — matches the spec's own
`pub:lorton` example (§7: "entry-only… live-verified, not a sample-data
artifact") and generalizes it: every entry-only node here is a reversible
express-lane endpoint the feed only prices trips *out of*.

**Exit-only (7):** Dumfries Rd (234), I-495 N, I-95 S near Backlick Rd,
Joplin Rd (619), Newington, Russell Rd, Washington DC.

**Pass-through (6) — all I-66 ITB:** Fairfax Drive, Glebe Road, Lee Highway,
Leesburg Pike, Spout Run Parkway, Sycamore Street. These have both incoming
and outgoing priced edges but never round-trip, because I-66 ITB's toll
zones are one-way gantry chains per direction — EB runs
Beltway→Lee Hwy→Fairfax Dr→Spout Run, WB runs
Glebe→Sycamore→Leesburg→Beltway — and `tests/test_graph.py`'s
`test_no_direct_i66_edge_crosses_eb_wb` already confirms there's no direct
edge back across directions. The only way back is through the Beltway
junction, which *is* in the core. Expected, not a gap.

## 3. Parallel edges

### 3a. Raw graph: 0 cross-node parallel edges

No raw `(from_node, to_node)` pair carries more than one price key. Every
bit of parallelism in the graph is introduced by the public merge (node
collapsing) — confirming §7's parallel-edge claim describes the *only*
source of duplication, not an emergent property already present in the raw
VDOT feed.

Raw self-loops: 8, all i66 same-zone pairs (`3100→3100` … `3230→3230`), as
documented in §4/§7.

### 3b. Public graph: 18 cross-node parallel groups (spec names 1)

| from | to | price keys |
|---|---|---|
| I-495 near MD | Springfield Interchange | od 1039, 1040, 1041 |
| I-495 near MD | Westpark Dr | od 1045, 1093 |
| I-66 / Beltway Interchange | Springfield Interchange | od 1073, 1074, 1075 |
| Jones Branch Dr | Springfield Interchange | od 1054, 1055, 1056 |
| Lee Hwy | Springfield Interchange | od 1078, 1079, 1080 |
| Route 7 | Springfield Interchange | od 1067, 1068, 1069 |
| Rt 267 (Dulles Access) | Springfield Interchange | od 1047, 1048, 1049 |
| Seminary Rd | Springfield Interchange | od 1215, 1216 |
| Springfield Interchange | I-495 N | od 1008, 1015, 1092 |
| Springfield Interchange | I-66 / Beltway Interchange | od 1003, 1010, 1087 |
| Springfield Interchange | Jones Branch Dr | od 1006, 1013, 1090 |
| Springfield Interchange | Lee Hwy | od 1002, 1009, 1086 |
| Springfield Interchange | Route 7 | od 1004, 1011, 1088 |
| Springfield Interchange | Rt 267 (Dulles Access) | od 1007, 1014, 1091 |
| Springfield Interchange | Westpark Dr | od 1005, 1012, 1089 |
| Washington Blvd / Pentagon | Springfield Interchange | od 1203, 1204 |
| **Westpark Dr** | **I-495 N** | **od 1000, 1037** *(the spec's example)* |
| Westpark Dr | Springfield Interchange | od 1061, 1062, 1063 |

**13 of the 18 groups touch `pub:springfield`** — unsurprising, since it
merges 7 raw Springfield-cluster nodes (§7's merge table), so any raw edge
into or out of *any* of those 7 collapses onto the same public pair as every
other. Every group here is a real distinct priced product per §7's rule
("never sum or dedupe them, take MIN for cheapest") — none look like data
errors; they're the expected fan-in from merging directional/duplicate raw
nodes.

### 3c. Public self-loops: 8 groups, one is doubly-keyed

| public node | price keys |
|---|---|
| Fairfax Drive | zone 3120→3120 |
| Glebe Road | zone 3200→3200 |
| **I-66 / Beltway Interchange** | **zone 3100→3100, zone 3230→3230** |
| Lee Highway | zone 3110→3110 |
| Leesburg Pike | zone 3220→3220 |
| Spout Run Parkway | zone 3130→3130 |
| Springfield Interchange | od 1001, 1083, 1084, 1085 |
| Sycamore Street | zone 3210→3210 |

7 of these are single-keyed and safe to treat as one price. `pub:i66-beltway`
is not: it merges `i66:capital-beltway-begin` (zone 3100→3100) and
`i66:capital-beltway-end` (zone 3230→3230) into one public node, so its
self-loop is really two distinct priced products, same as
`pub:springfield`'s four-way self-loop — it needs the same `MIN(price)` rule
§7 already prescribes for cross-node parallels, but §7's self-loop
discussion doesn't call this one out by name.

## 4. Findings

**F1 — Connectivity confirmed, exhaustively.** Both the raw and public
graphs are single connected components — no islands anywhere. The public
graph's directed asymmetry (8 entry-only + 7 exit-only + 6 pass-through
nodes around a 25-node core) is fully explained by known feed structure
(reversible express lanes, one-way I-66 zone chains) — nothing unexplained
turned up.

**F2 — Parallel edges are far more common than the one documented example.**
18 public `(from, to)` pairs carry multiple priced rows, not 1. The spec's
§7 wording ("e.g. …") doesn't claim exhaustiveness, so this isn't a
correctness bug — but a future reader skimming §7 could easily assume
Westpark→I-495 N is a rare/isolated case rather than one of 18, 13 of which
funnel through Springfield specifically. Worth a doc update if §7 is meant
to be a complete reference rather than an illustrative example.

**F3 — `pub:i66-beltway`'s self-loop is doubly-keyed, undocumented.**
Same "distinct products, take MIN" rule as Springfield's self-loop applies,
but §7 currently only names Springfield's 4-key self-loop as the
multi-keyed case. Any consumer pricing `pub:i66-beltway`'s self-loop as a
single lookup would be wrong the same way a naive Westpark lookup would be.

**F4 — No surprises in the raw graph.** Zero cross-node parallel edges at
the raw level confirms all duplication is a pure side effect of the public
merge, not something already lurking in the VDOT feed.

---

*This audit is read-only — it does not modify `db/graph.sql`,
`docs/toll-graph-spec.md`, or `tests/test_graph.py`. Analysis script used to
produce it was a scratch script, not committed.*
