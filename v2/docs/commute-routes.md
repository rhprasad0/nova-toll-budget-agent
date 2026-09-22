# Commute map road geometry

[`commute-routes.mjs`](../agent/assets/commute-routes.mjs) is a fixed **2026-09-22 OpenStreetMap snapshot**. It replaces the Census TIGER/Line 2019 overlay with the same underlying road dataset as the OpenFreeMap basemap. The browser downloads no OSM API data. Basemap snapshots and zoom-dependent simplification can differ from this overlay.

Geometry is **© OpenStreetMap contributors**, available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Preserve [OpenStreetMap attribution](https://www.openstreetmap.org/copyright) on the map and this data license when redistributing the geometry. The asset's `license`, `attribution`, and `sourceSnapshot` fields retain that provenance.

## Selection

Every `osm_way_ids` entry identifies the OSM way for the corresponding MultiLineString line. The parallel `way_movements` array records the supported facility, direction and access role for that line, such as `i495:SB:entry`. Coordinates retain source precision; no averaging, interpolated connectors, coordinate snapping, or simplification was applied.

| Mainline | Source relation | Selection | Ways |
| --- | --- | --- | ---: |
| I-66 | [1659168](https://www.openstreetmap.org/relation/1659168), v161 | `highway=motorway`, `name=Custis Memorial Parkway` | 105 |
| I-95 / I-395 | [1060711](https://www.openstreetmap.org/relation/1060711), v28; [8838159](https://www.openstreetmap.org/relation/8838159), v15 | `name=95 Express Lanes` or `ref=I 395 EXPR`, motorway only | 128 |
| I-495 | [2577685](https://www.openstreetmap.org/relation/2577685), v31 | `name=495 Express Lanes`, motorway only | 70 |
| Dulles Toll Road | [1541423](https://www.openstreetmap.org/relation/1541423), v109 | Relation mainline with `name=Dulles Toll Road` | 154 |
| Dulles Greenway | [1541423](https://www.openstreetmap.org/relation/1541423), v109 | Relation mainline with `name=Dulles Greenway` | 92 |

Named extensions supplement incomplete relation membership:

- I-95 toward Route 17: ways `1133277773`, `1133277781`, `1133277782`, `1202428321`.
- I-495 NEXT toward GW Memorial Parkway: ways `1411363408`, `1411363409`, `1411363411`, `1411363412`, `1411363413`, `1411363414`, `1489346948`, `1489346949`. The [official VDOT project map](https://495next.vdot.virginia.gov/project-resources/project-maps/) confirms the extension; the existing coverage snapshot includes its GWMP endpoints.

Do not filter solely by `toll=yes`: I-66 uses conditional tolling and parts of Dulles/Greenway are tagged `toll=no`. Do not filter solely by names: the I-395 express ways are unnamed, while their route relation retains an outdated HOV name. All selected I-95/I-395/I-495 mainline ways carry `toll=yes`. For example, [I-395 way 49037756](https://www.openstreetmap.org/way/49037756) runs along the reversible median; neighboring free mainline way `50658205` is excluded.

The Dulles overlay follows the continuous VA 267 through carriageways. It excludes the separate `Dulles Access Road` and the airport-side `VA 267 Toll` spur, including ways `8801478` and `8799377`. The Dulles/Greenway color boundary follows their source road names at the airport interchange; it is not a toll ownership boundary. Shared Route 28 coverage pins remain independent of that cartographic boundary. The [operator describes](https://www.dullestollroad.com/glance) the airport access highway, Greenway, and eastern Dulles Connector Road separately.

## Supported endpoints and access approaches

The five `role=mainline` features show physical corridor geometry. They stop at mapped mainline termini; supported access pins may sit on ramps beyond them. No straight line was drawn to force a mainline to a generalized pin. I-66 is limited to the inside-Beltway road; its old westward overextension is removed.

The `facility=i495`, `role=access` feature preserves the supported Van Dorn/TP1 connection using **ordinary Beltway carriageways**, displayed separately from express lanes. Both chains follow consecutive source nodes in their permitted direction:

- Westbound access to northbound express lanes: OSM node `622272902` → `64056097`, 15 ways.
- Southbound express lanes to eastbound access: OSM node `6005762747` → `622272884`, 19 ways.

The shared TP1 marker uses exported `tp1Coordinates = [-77.1538304, 38.7935663]`, the exact position of node `622272902`. This is a representative access location on one carriageway, not a toll gantry or a claim that the two directions share one lane. The access line ends and express mainline ends share exact source vertices; terminal access ways are clipped only at existing OSM nodes.

## Entrance ramps and marker placement

Eight `role=ramp` features contain **837 motorway-link ways** in 155 connected ramp components, including Route 17, Leesburg, GWMP and the Springfield interchange. Each component connects through actual OSM node IDs to a modeled mainline or a documented access approach. Selection follows permitted directions: an entrance ramp must reach the corresponding mainline, and an exit ramp must be reachable from it. Every segment of a retained way must allow the recorded movement. The selection stops at ordinary motorways or local roads; it does not traverse those roads to collect unrelated ramps. Ways tagged `access=no/private` or `motor_vehicle=no/private` are excluded.

An earlier undirected selection included 106 additional ways that require traveling against a one-way ramp to reach or leave a modeled corridor. Those ways are excluded, including the general-lane GWMP off-ramp `124083385`, airport/service-station branch `537602766`, and unrelated westbound I-66 Express branches `882176401`–`882176403`.

Ramp features use the primary `facility` for color and `facilities` for the corridors present in their permitted movements. Marker eligibility uses each line's `way_movements`, rather than the whole feature's facility list. These are access ramps; neither their color nor membership asserts that every ramp carries a toll.

Direction metadata is fixed with the snapshot, with no graph traversal in the browser. I-66 and I-495 carriageways use the source relations' east/west and north/south roles; connected I-495 extension ways inherit their carriageway's direction. Dulles/Greenway and the three one-way I-95/I-395 end chains use their complete directed chain termini, rather than the bearing of an individual bend. Reversible I-95/I-395 ways support both directions. Mainlines allow entrance and exit markers in their direction; the TP1 approach allows `i495:NB:entry`, and its departure allows `i495:SB:exit`. The Route 17 ordinary approach allows only `i95:NB:entry`.

For ramps, reverse traversal from each direction's mainline finds entrances, while forward traversal finds exits. The reversible I-95/I-395 mainline forms a source-node tree; orienting it from southern node `10566009316` identifies the local northbound and southbound tangents. At each road/ramp merge, the last incoming and first outgoing source segments must align: the cosine of their angle must exceed 0.25. This conservative display filter excludes opposite and nearly perpendicular joins instead of assuming both directions from a shared node. Ramp traversal retains its incoming segment to prevent immediate U-turns on reversible ways; ordinary signed left/right ramp junctions remain usable.

Source destination tags corroborate the movement examples: Seminary Road way `40253505` has `destination:ref=I 395 North` and permits only northbound entry; reversible way `40253503` permits northbound entry/southbound exit; `636701122` has `destination:ref:backward=I 395 South` and permits northbound exit/southbound entry. Reversible roads do not imply that every attached ramp supports both entry directions. These records describe physical connections, not current reversible-lane operating hours.

The complete 42-way Springfield express flyover component is included. One checked connection starts at I-95/I-395 mainline node `6003858541` and follows ramp ways `191328199`, `191326103`, `636701123`, `159458266`, `159458265`, `191328237`, `636701113`, `636701112`, and `696525976` onto the existing I-495 access carriageway, which reaches I-495 mainline node `64056097`. Every join uses a shared source node; apparent crossings without a shared node do not create a connection.

The renderer projects supported road markers onto the nearest mainline, ramp or access segment matching a supported facility, direction and entry/exit role within 500 metres. Airport markers retain their supplied coordinates; annual-estimate pins use the same displayed road position as their outbound origin. This changes display coordinates only, with no toll-rate, route-point database, graph or pricing changes.

At GWMP, southbound entrance `i495:180SO` uses approach way `26707566`, which joins express ramp `1448086167` at source node `292441942`. Nearby `26707564` is a northbound exit and is ineligible for that entrance. The I-66 Scott Street westbound entrance uses westbound way `1552305099`, even though the generalized source pin is closer to eastbound way `1552305101`.

Route 17 northbound origin `i95:234NO` lies on ordinary northbound I-95 before the express entrance. A separate `role=access` feature follows way `1020591635` from source node `390910` to `9413071231`, clipped only at existing nodes. It joins entrance ramps `1133277778` → `1133277777` → `1133277776` → `1133277775` → `1133277774`, reaching express mainline node `10566009316`. The marker moves about 0.9 metres onto that northbound approach. Nearby ramp `1159629368` and southern motorway `1202428321` carry southbound-only source tags and are ineligible. If a future marker has no eligible segment within 500 metres, it keeps its supplied coordinate.

The I-66 Route 123/Dolley Madison point (`i66:7:*`) is a deliberate feeder point: its registry source is `vdot_sr267_i66` on eastbound `SR00267EB`, the Dulles Connector Road leading to I-66. It keeps its I-66 identity but uses Dulles geometry for display projection; it must not jump several kilometres to the physical I-66 mainline. Its source coordinate is already about 1.4 metres from eastbound OSM way `38081414`.

## Refresh and checks

Download relation geometry with `https://api.openstreetmap.org/api/0.6/relation/{id}/full.json`. Supplemental named ways came from a bounded [Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) POST to `https://overpass-api.de/api/interpreter`, OSM base `2026-09-22T13:07:00Z`:

```overpass
[out:json][timeout:40];
way[highway=motorway][name~"Dulles|Express",i](38.15,-77.7,39.2,-77.0);
out tags geom;
```

TP1 came from `https://api.openstreetmap.org/api/0.6/map.json?bbox=-77.213,38.786,-77.150,38.804`, using only the source ways recorded on the access feature. Pin a refreshed snapshot in the asset, retain source way IDs, and inspect termini and any changed names before updating coverage. Keep API calls out of the page and CI.

The Route 17 northbound approach and its consecutive ramp joins were verified with `https://api.openstreetmap.org/api/0.6/map.json?bbox=-77.495,38.337,-77.463,38.368` on the same snapshot date. The ordinary approach is dashed rather than relabeled as express mainline.

Ramp geometry and node IDs came from the same Overpass endpoint, OSM base `2026-09-22T08:45:51Z`:

```overpass
[out:json][timeout:50];
way[highway=motorway_link](38.33,-77.58,39.11,-77.03);
out body geom;
```

That bounded query returned 2,926 ways. Shared-node selection found 943 connected ramp ways; permitted-direction checks retained 837. All selected ramp/mainline connection coordinates matched exactly despite the different snapshot times. Mainline ways absent from route relations had their node IDs verified using `https://api.openstreetmap.org/api/0.6/ways.json?ways={comma-separated-ids}`.

Relevant checks live in `v2/tests/test_dev_chat_ui.mjs` and `v2/tests/commute_map_browser.cjs`: provenance, finite regional coordinates, source-way/line/movement correspondence, actual I-395 median geometry, excluded free/airport mainlines and unrelated ramps, shared TP1 vertex, continuous Springfield ramp topology, direction-aware bounded marker projection, and browser rendering. Inspect overview plus I-395, Tysons, Reston, and Springfield close-ups. Asset delivery still uses the existing release manifest and digest checks.
