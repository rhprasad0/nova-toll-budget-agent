# NOVA Toll Graph — Network Due-Diligence Audit

**Generated:** 2026-07-22 · **Source of truth:** `db/graph.sql` (graph schema
v1.0.0) · **Spec:** `docs/toll-graph-spec.md`

## 1. Summary

This report audits the hand-curated toll-network graph the budget agent routes
on. The topology is **seed data someone typed in**, not machine-derived, so
before we stake project credibility on it we independently checked that every
node is a real, correctly-named place on the real highway network and that the
edge inventory matches what's actually in the seed.

**Graph size (verified against `db/graph.sql`):**

| | Count | Notes |
|---|---|---|
| Nodes | **60** | 34 `i95_express` + 18 `i495_express` + 8 `i66_itb` |
| Edges | **342** | 317 `feed='i95'` + 20 `feed='i66'` + 5 free junction connectors |

**Node-existence tally (60 nodes):**

| Verdict | Count | Meaning |
|---|---|---|
| ✅ VERIFIED | **37** | Named real exit / access ramp / road confirmed by an authoritative source |
| 🟡 PARTIAL | **23** | Abstract / directional / junction / HOV-ramp label that maps to real interchange geometry but not a single distinctly named public exit |
| ❌ UNVERIFIED | **0** | No node lacked a supporting source |

**Method:** three parallel researchers, one per corridor, found one
authoritative citation per node. Source hierarchy: VDOT / 511Virginia →
expresslanes.com (Transurban) → Virginia route/exit references (AARoads,
Wikipedia exit lists) → OpenStreetMap / Google Maps for interchange geometry.
Three citations were re-fetched as spot-checks and confirmed the claimed places
(Garrisonville/Gordon/PW Pkwy on AARoads I-95; Fairfax Dr / Spout Run / Lee Hwy
on AARoads I-66; Springfield Interchange on Wikipedia). One authoritative source
per node — no double-sourcing.

The **0 UNVERIFIED** result is the headline: every one of the 60 curated nodes
corresponds to a real, documentable place. The 23 PARTIAL nodes are not
errors — they're an artifact of how the VDOT feed names its OD-pair endpoints
(directional segments and interchange complexes rather than single signed
exits); see §5.

## 2. `i95_express` nodes (34) — I-95/395 Express Lanes

Garrisonville (Stafford) north to the Pentagon/DC. VA state-route numbers in
parentheses are the road each node sits on.

| node_id | name | verdict | source | justification |
|---|---|---|---|---|
| i95x:alban | Alban | ✅ | [army.mil](https://www.army.mil/article/121493/Ramp_to_connect_Fort_Belvoir_North_to_I_95/) | Express Lanes flyover ramp on Alban Rd to Fort Belvoir. |
| i95x:cardinal | Cardinal | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-south-prince-william-va) | Cardinal Dr overpass near Woodbridge (weigh-station marker). |
| i95x:dale-blvd | Dale Blvd | ✅ | [vdot](https://www.vdot.virginia.gov/news-events/news/northern-virginia-district/new-slip-ramp-from-southbound-i-95-general-purpose-lanes-to-95-express-lanes-south-of-dale-boulevard-in-prince-william-county-opening-tomorrow-dec-8.php) | SR 784, Exit 156; Express Lanes ramp opened Dec 2023. |
| i95x:dc-pentagon-washington-blvd | DC/Pentagon/Washington Blvd | 🟡 | [aaroads](https://www.aaroads.com/guides/i-395-north-va) | Compound label for the Exit 8 (SR 27) Pentagon/DC complex. |
| i95x:dumfries | Dumfries Rd (234) | ✅ | [wikipedia](https://en.wikipedia.org/wiki/Interstate_95_in_Virginia) | SR 234, Exit 152, Dumfries Road. |
| i95x:fairfax-county-pkwy | Fairfax County Pkwy (286) | ✅ | [wikipedia](https://en.wikipedia.org/wiki/Interstate_95_in_Virginia) | SR 286, Exit 166, Fairfax County Pkwy/Newington. |
| i95x:franconia-rd | Franconia Rd (644) | ✅ | [wikipedia](https://en.wikipedia.org/wiki/Interstate_95_in_Virginia) | SR 644, Exit 169-170, Springfield Interchange. |
| i95x:franconia-springfield-pkwy | Franconia-Springfield Pkwy (289) | ✅ | [wikipedia](https://en.wikipedia.org/wiki/Interstate_95_in_Virginia) | SR 289, Exit 169-170, Springfield Interchange. |
| i95x:garrisonville | Garrisonville Rd (610) | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-south-prince-william-va) | SR 610, Exit 143; original southern terminus of Express Lanes. |
| i95x:gordon-blvd | Gordon Blvd (123) | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-south-prince-william-va) | SR 123, Exit 160, Gordon Blvd/Occoquan Rd. |
| i95x:i395-95 | I-395/95 | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Springfield_Interchange) | Springfield "Mixing Bowl" junction, not a single named exit. |
| i95x:i395-n | I-395 N | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Interstate_395_(Virginia%E2%80%93District_of_Columbia)) | Directional segment label for the I-395 corridor. |
| i95x:i495-springfield | I-495 (Springfield) | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Springfield_Interchange) | Same Mixing Bowl junction complex; also the Springfield junction node. |
| i95x:i95-s-ft-belvoir | I-95 S / Ft Belvoir | 🟡 | [army.mil](https://home.army.mil/belvoir/about/visitor-information) | Real Exit 161B (US 1) to Fort Belvoir, but directional/compound label. |
| i95x:i95-s-near-backlick-rd | I-95 S near Backlick Rd | 🟡 | [aaroads](https://www.aaroads.com/guides/i-095-south-fairfax-va) | Slip ramp opposite Exit 167 to Backlick Rd; directional, not a formal exit. |
| i95x:i95-s-near-dale-blvd | I-95 S near Dale Blvd | 🟡 | [vdot](https://www.vdot.virginia.gov/news-events/news/northern-virginia-district/new-slip-ramp-from-southbound-i-95-general-purpose-lanes-to-95-express-lanes-south-of-dale-boulevard-in-prince-william-county-opening-tomorrow-dec-8.php) | Real slip ramp, directional label distinct from the Dale Blvd exit. |
| i95x:joplin-rd | Joplin Rd (619) | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-south-prince-william-va) | SR 619, Exit 150 near Quantico/Triangle. |
| i95x:lorton | Lorton | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-north-fairfax-va) | Exit 163 (SR 642) Express Lanes access near Lorton. |
| i95x:newington | Newington | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-north-fairfax-va) | Exit 166 area; named Express Lanes access point. |
| i95x:old-courthouse-rd | Old Courthouse Rd | ✅ | [fredericksburg.com](https://fredericksburg.com/news/local/new-interstate-95-express-lanes-exits-to-open-stafford-route-630-courthouse-road-i-95/article_6f51c2e6-8e08-11ee-a0bd-43a3647a72dd.html) | SR 630, new Express Lanes ramp in Stafford. |
| i95x:opitz | Opitz | ✅ | [vdot](https://www.vdot.virginia.gov/news-events/news/northern-virginia-district/95-express-lanes-opitz-boulevard-ramp-to-open.html) | Opitz Blvd direct Express Lanes ramp, opened Nov 2024. |
| i95x:pentagon | Pentagon | ✅ | [expresslanes.com](https://www.expresslanes.com/learn-the-lanes) | Dedicated signalized Pentagon ramp off I-395 Express Lanes. |
| i95x:prince-william-pkwy | Prince William Pkwy (294) | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-south-prince-william-va) | SR 294, Exit 158, Prince William Parkway. |
| i95x:quantico | Quantico | ✅ | [iexit](https://www.iexitapp.com/Virginia/I-95/Exit%20148/4864) | Town/MCB Quantico, I-95 Exits 148 & 150. |
| i95x:rt17-95-nb | Rt 17 / 95 NB | 🟡 | [fredericksburg.com](https://fredericksburg.com/news/local/new-interstate-95-express-lanes-exits-to-open-stafford-route-630-courthouse-road-i-95/article_6f51c2e6-8e08-11ee-a0bd-43a3647a72dd.html) | Real flyover ramp near Rt 17 in Stafford; directional label. |
| i95x:rt17-95-sb | Rt 17 / 95 SB | 🟡 | [fredericksburg.com](https://fredericksburg.com/news/local/new-interstate-95-express-lanes-exits-to-open-stafford-route-630-courthouse-road-i-95/article_6f51c2e6-8e08-11ee-a0bd-43a3647a72dd.html) | Same Rt 17 interchange, southbound; directional label. |
| i95x:russell-rd | Russell Rd | ✅ | [aaroads](https://www.aaroads.com/guides/i-095-south-prince-william-va) | Exit 148, Russell Rd, MCB Quantico access. |
| i95x:seminary-rd | Seminary Rd | ✅ | [aaroads](https://www.aaroads.com/guides/i-395-north-va) | SR 420, Exit 4 on I-395; named Express Lanes exit. |
| i95x:shirlington-circle | Shirlington Circle | ✅ | [aaroads](https://www.aaroads.com/guides/i-395-north-va) | Exit 6, rotary interchange with Quaker Lane at Shirlington. |
| i95x:telegraph-rd | Telegraph Rd | ✅ | [wikipedia](https://en.wikipedia.org/wiki/Virginia_State_Route_611_(Fairfax_County)) | SR 611; I-95/I-495 Telegraph Rd interchange near Springfield. |
| i95x:turkeycock | Turkeycock | ✅ | [aaroads](https://www.aaroads.com/guides/i-395-north-va) | Turkeycock Run interchange/stream valley; I-395 Express ingress. |
| i95x:us-1 | US 1 | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Interstate_95_in_Virginia) | US 1 crosses I-95 at multiple points (Exit 143, 161); not one ramp. |
| i95x:washington-blvd-pentagon | Washington Blvd / Pentagon | ✅ | [aaroads](https://www.aaroads.com/guides/i-395-north-va) | SR 27, Exit 8, Washington Blvd to Pentagon/Arlington Cemetery. |
| i95x:washington-dc | Washington DC | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Interstate_395_(Virginia%E2%80%93District_of_Columbia)) | I-395 DC terminus; abstract destination, not a single exit. |

## 3. `i495_express` nodes (18) — I-495 Capital Beltway Express Lanes

Springfield interchange north to the 495 NEXT extension near the Maryland line.

| node_id | name | verdict | source | justification |
|---|---|---|---|---|
| i495x:braddock | Braddock Rd | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Exit 54, SR 620 Braddock Road; dedicated Express Lanes ramp. |
| i495x:gallows | Gallows Rd | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-north-tysons-va) | Exit 51, SR 650 Gallows Road; dedicated Express Lanes ramp. |
| i495x:i395-495-hov | I-395-495 HOV | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Springfield_Interchange) | Phase 8 HOV/HOT connector linking I-395 and I-495; not a named exit. |
| i495x:i395-95-495 | I-395-95-495 | 🟡 | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Exit 57, Springfield Interchange merge of the Express Lanes. |
| i495x:i395-95-hov | I-395-95 HOV | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Springfield_Interchange) | Reversible Shirley Hwy HOV lanes tie in at Springfield; junction. |
| i495x:i495-hov | I-495 HOV | 🟡 | [expresslanes.com](https://www.expresslanes.com/faqs) | HOV-3+ exemption on I-495 Express Lanes generally; no single exit. |
| i495x:i495-n | I-495 N | 🟡 | [aaroads](https://www.aaroads.com/guides/i-495-north-tysons-va) | Directional label for I-495 Express Lanes NB mainline. |
| i495x:i495-near-md | I-495 near MD | 🟡 | [expresslanes.com](https://expresslanes.com/495Extension) | 495 NEXT northern end near American Legion Bridge/MD line (opened Nov 2025). |
| i495x:i66-jct | I-66 | 🟡 | [aaroads](https://www.aaroads.com/guides/i-495-north-tysons-va) | Exit 49 connector to I-66 / I-66 Express Lanes; junction node. |
| i495x:i95-hov | I-95 HOV | 🟡 | [wikipedia](https://en.wikipedia.org/wiki/Springfield_Interchange) | I-95 Express/HOV connect to I-495 via Springfield connectors. |
| i495x:jones-branch | Jones Branch Dr | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-north-tysons-va) | Dedicated HOT-lane exit for Jones Branch Dr in Tysons. |
| i495x:jones-branch-rt267 | Jones Branch Dr / Rt 267 | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-north-tysons-va) | Exit 45 ramp splits to Jones Branch Dr and SR 267 west. |
| i495x:lee-hwy | Lee Hwy | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Exit 50, US 29 Lee Highway ramp. |
| i495x:route-7 | Route 7 | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-inner-loop-va) | Exit 47, SR 7 Leesburg Pike ramps on Express Lanes. |
| i495x:rt-267 | Rt 267 | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Exit 45, SR 267 Dulles Toll Road/Airport access. |
| i495x:westpark | Westpark Dr | ✅ | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Exit 46, dedicated Westpark Dr Express Lanes ramp in Tysons. |
| i495x:westpark-b | Westpark Dr (B) | 🟡 | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Curated duplicate label for the same Exit 46 Westpark Dr access (see §5). |
| i495x:westpark-c | Westpark Dr (C) | 🟡 | [aaroads](https://www.aaroads.com/guides/i-495-outer-loop-va/) | Curated duplicate label for the same Exit 46 Westpark Dr access (see §5). |

## 4. `i66_itb` nodes (8) — I-66 Inside the Beltway toll zones

Eight tolling zones — four eastbound (Beltway → Rosslyn), four westbound. Zone
IDs come straight from the VDOT feed.

| node_id | name | zone / dir | verdict | source | justification |
|---|---|---|---|---|---|
| i66:capital-beltway-begin | Capital Beltway Beginning | 3100 EB | 🟡 | [vdot Transform66](https://www.vdot.virginia.gov/projects/major-projects/transform66/transform66-inside/) | I-66/I-495 terminal interchange (AARoads Exit 64); toll-zone boundary, not a named exit. |
| i66:lee-highway | Lee Highway | 3110 EB | ✅ | [aaroads](https://www.aaroads.com/guides/i-066-east-fairfax-va) | US-29 Lee Highway, confirmed I-66 ITB interchange. |
| i66:fairfax-dr | Fairfax Drive | 3120 EB | ✅ | [aaroads](https://www.aaroads.com/guides/i-066-east-fairfax-va) | Exit 71, Fairfax Dr (SR-237) wye into Ballston. |
| i66:spout-run | Spout Run Parkway | 3130 EB | ✅ | [aaroads](https://www.aaroads.com/guides/i-066-east-fairfax-va) | Exit 72, adjacent to Spout Run Pkwy near Rosslyn. |
| i66:glebe-rd | Glebe Road | 3200 WB | ✅ | [aaroads](https://www.aaroads.com/guides/i-066-east-fairfax-va) | SR-120 Glebe Road half-diamond interchange. |
| i66:sycamore-st | Sycamore Street | 3210 WB | ✅ | [aaroads](https://www.aaroads.com/guides/i-066-west-fairfax-va) | Exit 69 split diamond near East Falls Church Metro. |
| i66:leesburg-pike | Leesburg Pike | 3220 WB | ✅ | [aaroads](https://www.aaroads.com/guides/i-066-west-fairfax-va) | Exit 66, SR-7 Leesburg Pike. |
| i66:capital-beltway-end | Capital Beltway End | 3230 WB | 🟡 | [aaroads](https://www.aaroads.com/guides/i-066-west-fairfax-va) | I-66/I-495 terminal interchange (Exit 64); toll-zone boundary, not a named exit. |

## 5. Edge inventory (342 edges)

Edges are **not independently citable** — each is a priced OD-pair or zone-pair
*combination* of two nodes proven above. Per the spec, every dynamic edge is a
complete priced trip, never a segment to be summed (`docs/toll-graph-spec.md`
§1, §3).

### 5a. i95/i495 dynamic edges — 317 (`feed='i95'`, keyed `od_pair_id`)

`od_pair_id` ranges **1000–1352** (with gaps — 353 slots, 317 used — reflecting
OD pairs VDOT prices vs. the contiguous ID space). These form origin×destination
matrices within and between the I-95/395 and I-495 Express Lanes; e.g.
Springfield-area origins (`i495x:i395-95-hov`, `i495x:i395-95-495`,
`i495x:braddock`…) each fan out to the northbound I-495 destination set
(`lee-hwy`, `i66-jct`, `route-7`, `westpark`, `jones-branch`, `rt-267`,
`i495-n`), and the I-95 corridor origins (`garrisonville`, `quantico`,
`turkeycock`…) fan out to the northern I-95 destination set. Representative rows:

| from_node | to_node | od_pair_id |
|---|---|---|
| i495x:westpark-b | i495x:i495-n | 1000 |
| i495x:i395-95-hov | i495x:lee-hwy | 1002 |
| i95x:garrisonville | i95x:gordon-blvd | 1094 |
| i95x:turkeycock | i95x:garrisonville | 1157 |

### 5b. i66 dynamic edges — 20 (`feed='i66'`, keyed `start_zone_id`/`end_zone_id`)

The complete triangular set of zone pairs *within each direction* — 10 EB + 10
WB — including same-zone trips (e.g. `3100→3100`), which are legitimately priced
products in the feed. Full list (small enough to show in full):

| direction | zone pairs |
|---|---|
| **EB** (3100 Beltway-begin, 3110 Lee Hwy, 3120 Fairfax Dr, 3130 Spout Run) | 3100→3100, 3100→3110, 3100→3120, 3100→3130, 3110→3110, 3110→3120, 3110→3130, 3120→3120, 3120→3130, 3130→3130 |
| **WB** (3200 Glebe, 3210 Sycamore, 3220 Leesburg Pike, 3230 Beltway-end) | 3200→3200, 3200→3210, 3200→3220, 3200→3230, 3210→3210, 3210→3220, 3210→3230, 3220→3220, 3220→3230, 3230→3230 |

### 5c. Free junction connectors — 5 (`feed IS NULL`, no price lookup)

The express-lane ramps and interchange gores that carry no toll but stitch the
three corridors into one connected graph:

| from_node | to_node | movement |
|---|---|---|
| i95x:i495-springfield | i495x:i395-95-hov | Springfield NB: I-95 Express → I-495 Express |
| i495x:i95-hov | i95x:i495-springfield | Springfield SB: continue south on I-95 Express |
| i495x:i395-495-hov | i95x:i495-springfield | Springfield: continue north on reversible I-395 lanes |
| i495x:i66-jct | i66:capital-beltway-begin | Beltway → I-66 EB |
| i66:capital-beltway-end | i495x:i66-jct | I-66 WB → Beltway |

## 6. Due-diligence findings

**F1 — Stale edge counts in code comment and spec traversal contract.**
`db/graph.sql:93` reads *"Edges (341) … junction connectors (4, feed NULL)"* and
the spec's Traversal Contract (`docs/toll-graph-spec.md` §, lines 249 & 251)
also says **341 edges** — but the actual seed has **342 edges / 5 junction
connectors**, which matches the spec's *own* §1 count (line 55: "60 nodes, 342
edges") and §1 prose. So the seed and the spec's §1 are correct; the inline
comment and the traversal-contract number are stale.
*Recommended follow-up (not applied here):* fix the `graph.sql:93` comment
(341→342, 4→5) and the two "341" mentions in the spec's Traversal Contract.

**F2 — Three nodes map to one physical exit (Westpark Dr).** `i495x:westpark`,
`i495x:westpark-b`, and `i495x:westpark-c` all resolve to the same Exit 46
Westpark Dr access in Tysons. They exist as distinct nodes to carry distinct
OD-pair endpoints the feed prices separately — legitimate, but worth knowing
they are **not three separate physical exits**. Anything presenting node names
to a user should not imply three different Westpark locations.

**F3 — 23 PARTIAL nodes are directional/junction labels, by design.** These
(11 on i95_express, 10 on i495_express, 2 on i66_itb) map to real geometry —
mostly the Springfield "Mixing Bowl", the Pentagon/Exit 8 complex, the Rt 17
Stafford ramps, and the I-66×I-495 interchange — rather than a single signed
public exit. This is inherent to how the VDOT feed names OD-pair endpoints
(directional segments, HOV-ramp tie-ins, multi-route junctions). Not errors,
but **lower-confidence for any consumer that assumes one node = one signed
exit**. The graph never re-parses these names at runtime (it joins on numeric
`od_pair_id` / zone IDs per spec §6), so the ambiguity stays cosmetic.

**F4 — 0 UNVERIFIED nodes.** Every one of the 60 curated nodes corresponds to a
real, documentable place. For a hand-typed seed, that's a clean bill of health
on existence.

### Confidence at a glance

| Corridor | Nodes | ✅ VERIFIED | 🟡 PARTIAL | ❌ UNVERIFIED |
|---|---|---|---|---|
| i95_express | 34 | 23 | 11 | 0 |
| i495_express | 18 | 8 | 10 | 0 |
| i66_itb | 8 | 6 | 2 | 0 |
| **Total** | **60** | **37** | **23** | **0** |

---

*Citations reflect sources as of 2026-07-22; one authoritative source per node.
The graph corridors, junction rationale, and zone table are documented in
`docs/toll-graph-spec.md`; this audit cross-checks that seed against external
references and does not modify it.*
