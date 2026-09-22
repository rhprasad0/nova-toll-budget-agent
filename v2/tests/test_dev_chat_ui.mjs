import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MAX_RAW_EVENT_LOG_CHARS,
  STARTER_PROMPTS,
  applyEvent,
  consumeNdjson,
  validStreamEvent,
} from "../agent/dev_chat.mjs";
import { renderAssistantMarkdown } from "../agent/assets/chat-markdown.mjs";
import * as commuteMap from "../agent/assets/commute-map.mjs";
import { routeData, tp1Coordinates } from "../agent/assets/commute-routes.mjs";

const { formatAnnualToll, validateEstimateSnapshot } = commuteMap;

/** @type {import("../agent/assets/commute-map.mjs").EstimateSnapshot} */
const commuteEstimates = JSON.parse(await readFile(
  new URL("../agent/assets/commute-estimates.json", import.meta.url),
  "utf8",
));

/** @param {number[]} point @param {number[][]} line */
const pointOnLine = ([longitude, latitude], line) => line.some(([x, y], index) => {
  if (!index) return false;
  const [previousX, previousY] = line[index - 1];
  // Triangle equality verifies membership without repeating the projection algorithm.
  return Math.abs(Math.hypot(longitude - previousX, latitude - previousY)
    + Math.hypot(longitude - x, latitude - y)
    - Math.hypot(x - previousX, y - previousY)) < 1e-10;
});

/** @param {...string} chunks */
const stream = (...chunks) => new ReadableStream({
  start(controller) {
    for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
    controller.close();
  },
});

const fakeView = () => {
  const raw = {
    value: "",
    writes: 0,
    get textContent() { return this.value; },
    set textContent(value) { this.value = value; this.writes += 1; },
  };
  return {
    activities: { append() {} },
    answer: { classList: { add() {} }, innerHTML: "", textContent: "" },
    article: {
      scrolls: 0,
      scrollIntoView() { this.scrolls += 1; },
    },
    details: { open: false },
    items: new Map(),
    raw,
    rawChars: 0,
    rawEvents: [],
    rawTruncated: false,
    renderFrame: null,
    text: "",
  };
};

test("consumes split NDJSON events through one terminal result", async () => {
  /** @type {import("../agent/dev_chat.mjs").StreamEvent[]} */
  const seen = [];
  await consumeNdjson(stream(
    '{"type":"event","sequence":0,"event":{"data":"Hi 👋"},"text_',
    'delta":"Hi 👋"}\n{"type":"event","sequence":1,"event":{"result":{}},',
    '"final":{"text":"Hi 👋","metrics":{}}}\n',
  ), (event) => seen.push(event));

  assert.equal(seen.length, 2);
  assert.equal(seen[0].text_delta, "Hi 👋");
  assert.equal(seen[1].final?.text, "Hi 👋");
});

test("rejects malformed and unterminated streams", async () => {
  await assert.rejects(() => consumeNdjson(stream("not json\n"), () => {}));
  await assert.rejects(
    () => consumeNdjson(
      stream('{"type":"event","sequence":0,"event":{}}\n'),
      () => {},
    ),
    /missing terminal event/,
  );
  assert.equal(validStreamEvent({ type: "event", sequence: -1, event: {} }), false);
});

test("bounds raw events and batches streamed Markdown into one animation frame", () => {
  // These two browser APIs are deliberately supplied by this Node test.
  const animationGlobals = /** @type {{requestAnimationFrame?: typeof requestAnimationFrame, cancelAnimationFrame?: typeof cancelAnimationFrame}} */ (globalThis);
  const originalRequest = animationGlobals.requestAnimationFrame;
  const originalCancel = animationGlobals.cancelAnimationFrame;
  /** @type {Map<number, FrameRequestCallback>} */
  const frames = new Map();
  let nextFrame = 0;
  animationGlobals.requestAnimationFrame = (callback) => {
    const id = ++nextFrame;
    frames.set(id, callback);
    return id;
  };
  animationGlobals.cancelAnimationFrame = (id) => frames.delete(id);

  try {
    const closed = fakeView();
    for (let sequence = 0; sequence < 100; sequence += 1) {
      applyEvent(closed, {
        type: "event",
        sequence,
        event: { payload: "x".repeat(1024) },
      });
    }
    assert.equal(closed.raw.writes, 0);
    assert.equal(closed.raw.textContent, "");
    assert.ok(closed.rawChars < MAX_RAW_EVENT_LOG_CHARS);
    closed.details.open = true;
    applyEvent(closed, { type: "event", sequence: 100, event: {} });
    assert.equal(closed.raw.writes, 1);
    assert.equal(closed.raw.textContent.length, MAX_RAW_EVENT_LOG_CHARS);
    assert.match(closed.raw.textContent, /^Earlier events omitted[.]\n/);

    const streaming = fakeView();
    applyEvent(streaming, {
      type: "event", sequence: 0, event: {}, text_delta: "Hello ",
    });
    applyEvent(streaming, {
      type: "event", sequence: 1, event: {}, text_delta: "**driver** 👋",
    });
    assert.equal(frames.size, 1);
    assert.equal(streaming.answer.innerHTML, "");
    assert.equal(streaming.article.scrolls, 0);

    const [frameId, render] = /** @type {[number, FrameRequestCallback]} */ (frames.entries().next().value);
    frames.delete(frameId);
    render(0);
    assert.match(streaming.answer.innerHTML, /Hello <strong>driver<\/strong> 👋/);
    assert.equal(streaming.article.scrolls, 1);

    applyEvent(streaming, {
      type: "event", sequence: 2, event: {}, text_delta: " partial",
    });
    assert.equal(frames.size, 1);
    applyEvent(streaming, {
      type: "event",
      sequence: 3,
      event: {},
      final: { text: "## Final 👋", metrics: {} },
    });
    assert.equal(frames.size, 0);
    assert.match(streaming.answer.innerHTML, /<h2>Final 👋<\/h2>/);
    assert.equal(streaming.article.scrolls, 2);

    applyEvent(streaming, {
      type: "event", sequence: 4, event: {}, text_delta: " stale",
    });
    assert.equal(frames.size, 1);
    applyEvent(streaming, {
      type: "error", sequence: 5, message: "Request failed",
    });
    assert.equal(frames.size, 0);
    assert.equal(streaming.answer.textContent, "Request failed");
    assert.equal(streaming.article.scrolls, 3);
  } finally {
    if (originalRequest) animationGlobals.requestAnimationFrame = originalRequest;
    else delete animationGlobals.requestAnimationFrame;
    if (originalCancel) animationGlobals.cancelAnimationFrame = originalCancel;
    else delete animationGlobals.cancelAnimationFrame;
  }
});

test("renders supported Markdown and emoji while hostile content stays inert", () => {
  const html = renderAssistantMarkdown(
    "## Price 👋\n\n**$4.25** [safe](https://example.com) "
      + "[bad](javascript:alert(1)) <img src=x onerror=alert(1)> ![alt](https://x.test/x.png)",
  );

  assert.match(html, /<h2>Price 👋<\/h2>/);
  assert.match(html, /<strong>\$4\.25<\/strong>/);
  assert.match(html, /href="https:\/\/example\.com"/);
  assert.doesNotMatch(html, /href="javascript:|<img/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /alt/);
});

test("starter prompts are complete enough to submit without clarification", () => {
  assert.deepEqual(STARTER_PROMPTS, [
    "What is the current price from Dumfries to Washington?",
    "How much take-home pay would I have after commuting from Leesburg to Washington on "
      + "Mondays and Fridays, leaving at 8:30 AM and returning at 5:30 PM for 96 days a "
      + "year, on a $130,000 gross annual salary?",
  ]);
});

test("checked-in estimate snapshot contains the four approved Washington commutes", () => {
  const snapshot = validateEstimateSnapshot(commuteEstimates);

  assert.equal(snapshot.schema_version, 1);
  assert.equal(snapshot.destination, "Washington, DC");
  assert.deepEqual(snapshot.assumptions.weekdays, [
    "monday", "tuesday", "wednesday", "thursday", "friday",
  ]);
  assert.equal(snapshot.assumptions.outbound_departure_time, "08:30:00");
  assert.equal(snapshot.assumptions.return_departure_time, "17:30:00");
  assert.equal(snapshot.assumptions.planned_annual_commute_days, 240);
  assert.deepEqual(
    snapshot.estimates.map(({ id }) => id),
    ["dumfries", "springfield-franconia", "leesburg", "i66-west"],
  );
  assert.deepEqual(snapshot.estimates.map(({ outbound, return: returnTrip }) => [
    outbound.origin_point_id,
    outbound.destination_point_id,
    returnTrip.origin_point_id,
    returnTrip.destination_point_id,
  ]), [
    ["i95:218NO", "i95:224ND", "i95:2232SO", "i95:217SD"],
    ["i95:206NO", "i95:224ND", "i95:2232SO", "i95:206SD"],
    ["greenway:1:entry:EB", "i66:16:exit:EB", "i66:16:entry:WB", "greenway:1:exit:WB"],
    ["i66:1:entry:EB", "i66:16:exit:EB", "i66:16:entry:WB", "i66:1:exit:WB"],
  ]);
  for (const estimate of snapshot.estimates) {
    assert.match(formatAnnualToll(estimate.scenarios.p50.annual_toll_usd), /^\$[\d,]+\/yr$/);
    assert.ok(Number(estimate.scenarios.p25.annual_toll_usd) <= Number(estimate.scenarios.p50.annual_toll_usd));
    assert.ok(Number(estimate.scenarios.p50.annual_toll_usd) <= Number(estimate.scenarios.p90.annual_toll_usd));
  }
});

test("annual estimate inputs preserve oracle coordinates and pin tips have no visual offsets", async () => {
  const source = await readFile(
    new URL("../agent/assets/commute-map.mjs", import.meta.url),
    "utf8",
  );
  const estimateMarkerLoop = source.slice(
    source.indexOf("for (const estimate of snapshot.estimates)"),
    source.indexOf("const destination = document.createElement"),
  );
  assert.match(estimateMarkerLoop, /new maplibregl[.]Marker/);
  assert.match(estimateMarkerLoop, /pin[.]className = "estimate-pin"/);
  assert.match(estimateMarkerLoop, /pin[.]append\(marker\)/);
  assert.match(estimateMarkerLoop, /element: pin/);
  assert.doesNotMatch(estimateMarkerLoop, /\boffset\s*:/);

  const page = await readFile(new URL("../agent/assets/chat.css", import.meta.url), "utf8");
  assert.match(page, /[.]estimate-pin \{[^}]*padding-bottom:11px;/);
  assert.doesNotMatch(page, /transform:translateY\(-7px\)/);

  const coverage = commuteMap.validateCoverageLocations(JSON.parse(await readFile(
    new URL("../agent/assets/coverage-locations.json", import.meta.url),
    "utf8",
  )));
  const coordinatesByPoint = new Map(coverage.locations.flatMap((location) => (
    location.points.map(({ point_id: pointId }) => [pointId, location.coordinates])
  )));
  for (const estimate of commuteEstimates.estimates) {
    assert.deepEqual(
      estimate.coordinates,
      coordinatesByPoint.get(estimate.outbound.origin_point_id),
    );
  }
});

test("estimate validation rejects malformed or unsafe map data", () => {
  assert.throws(() => validateEstimateSnapshot({}), /invalid commute estimate snapshot/);
  assert.throws(
    () => validateEstimateSnapshot({ ...commuteEstimates, estimates: commuteEstimates.estimates.slice(1) }),
    /invalid commute estimate snapshot/,
  );
  assert.throws(
    () => validateEstimateSnapshot({
      ...commuteEstimates,
      estimates: commuteEstimates.estimates.map((estimate, index) => index
        ? estimate
        : { ...estimate, coordinates: ["secret", 38.5] }),
    }),
    /invalid commute estimate snapshot/,
  );
});

test("checked-in coverage snapshot contains every grouped v2 oracle point", async () => {
  const snapshot = commuteMap.validateCoverageLocations(JSON.parse(await readFile(
    new URL("../agent/assets/coverage-locations.json", import.meta.url),
    "utf8",
  )));

  assert.equal(snapshot.schema_version, 1);
  assert.equal(snapshot.locations.length, 103);
  const records = snapshot.locations.flatMap(({ points }) => points);
  assert.equal(records.length, 220);
  assert.equal(new Set(records.map(({ point_id: pointId }) => pointId)).size, 220);
  const tp1 = snapshot.locations.find(({ coordinates }) => (
    coordinates[0] === -77.15413222704926 && coordinates[1] === 38.79347384215561
  ));
  assert.ok(tp1);
  assert.deepEqual(tp1.points.map(({ label, direction, role }) => ({ label, direction, role })), [
    {
      label: "I-495 Express northbound start at I-95 (TP1NB)",
      direction: "NB",
      role: "entry",
    },
    {
      label: "I-495 Express southbound end at I-95 (TP1SB)",
      direction: "SB",
      role: "exit",
    },
  ]);
});

test("coverage validation rejects malformed coordinates and access records", () => {
  const location = {
    coordinates: [-77.15, 38.79],
    points: [{
      point_id: "i495:192NO",
      facility: "i495",
      label: "I-495 Express northbound start at I-95 (TP1NB)",
      direction: "NB",
      role: "entry",
    }],
  };
  assert.equal(commuteMap.validateCoverageLocations({
    schema_version: 1,
    locations: [location],
  }).locations[0], location);
  const distant = { ...location, coordinates: [-78, 38] };
  assert.equal(commuteMap.coverageCoordinates(distant), distant.coordinates);
  assert.throws(
    () => commuteMap.validateCoverageLocations({
      schema_version: 1,
      locations: [{ ...location, coordinates: ["secret", 38.79] }],
    }),
    /invalid coverage location snapshot/,
  );
  assert.throws(
    () => commuteMap.validateCoverageLocations({
      schema_version: 1,
      locations: [{
        ...location,
        points: [{ ...location.points[0], role: "maybe" }],
      }],
    }),
    /invalid coverage location snapshot/,
  );
});

test("coverage details expose readable names and directions but not point IDs", () => {
  const location = {
    coordinates: [-77.15, 38.79],
    points: [
      {
        point_id: "i495:192NO",
        facility: "i495",
        label: "I-495 Express northbound start at I-95 (TP1NB)",
        direction: "NB",
        role: "entry",
      },
      {
        point_id: "i495:192SD",
        facility: "i495",
        label: "I-495 Express southbound end at I-95 (TP1SB)",
        direction: "SB",
        role: "exit",
      },
    ],
  };
  const detail = commuteMap.coverageDetail(location);

  assert.equal(detail.kicker, "Supported route point");
  assert.equal(detail.title, "I-495/I-95 near Van Dorn Street");
  assert.deepEqual(detail.paragraphs, [
    "Northbound entrance · Southbound exit",
    "The dashed connection follows the Beltway approach to the express lanes.",
  ]);
  assert.deepEqual(commuteMap.coverageCoordinates(location), tp1Coordinates);
  assert.doesNotMatch(JSON.stringify(detail), /i495:192/);
});

test("OSM corridors retain attribution, way provenance and valid regional geometry", async () => {
  assert.equal(routeData.source, "OpenStreetMap contributors");
  assert.equal(routeData.attribution, "https://www.openstreetmap.org/copyright");
  assert.equal(routeData.license, "https://opendatacommons.org/licenses/odbl/1-0/");
  assert.match(routeData.sourceSnapshot, /^\d{4}-\d{2}-\d{2}$/);
  const mainlines = routeData.features.filter(({ properties }) => properties.role === "mainline");
  assert.deepEqual(mainlines.map(({ properties }) => properties.facility), [
    "i66", "i95", "i495", "dulles", "greenway",
  ]);
  const wayIds = routeData.features.flatMap(({ properties }) => properties.osm_way_ids);
  assert.equal(new Set(wayIds).size, wayIds.length, "shared ramps are represented once");
  for (const { properties, geometry } of routeData.features) {
    assert.equal(geometry.type, "MultiLineString");
    assert.equal(properties.osm_way_ids.length, geometry.coordinates.length);
    assert.equal(properties.way_movements.length, geometry.coordinates.length);
    for (const movements of properties.way_movements) {
      assert.ok(movements.length > 0);
      assert.equal(new Set(movements).size, movements.length);
      assert.ok(movements.every((movement) => /^(i66|i95|i495|dulles|greenway):(NB|SB|EB|WB):(entry|exit)$/.test(movement)));
    }
    assert.equal(new Set(properties.osm_way_ids).size, properties.osm_way_ids.length);
    assert.ok(properties.osm_way_ids.every((id) => Number.isSafeInteger(id) && id > 0));
    assert.ok(!properties.sourceNames.includes("Dulles Access Road"));
    for (const line of geometry.coordinates) {
      assert.ok(line.length >= 2);
      for (const [longitude, latitude] of line) {
        assert.ok(Number.isFinite(longitude) && longitude > -77.7 && longitude < -77);
        assert.ok(Number.isFinite(latitude) && latitude > 38.15 && latitude < 39.2);
      }
    }
  }
  // A fresh module instance catches accidental render-time trims or connectors.
  const pristine = await import(new URL("../agent/assets/commute-routes.mjs?data-integrity", import.meta.url).href);
  assert.deepEqual(routeData, pristine.routeData);
});

test("corridors select express lanes and exclude the Dulles airport spur", () => {
  const i95 = routeData.features.find(({ properties }) => properties.facility === "i95");
  const dulles = routeData.features.find(({ properties }) => properties.facility === "dulles");
  const i66 = routeData.features.find(({ properties }) => properties.facility === "i66");
  assert.ok(i95 && dulles && i66);
  // OSM 49037756 is the reversible I-395 express carriageway; 50658205 is free I-395.
  const expressIndex = i95.properties.osm_way_ids.indexOf(49037756);
  assert.ok(expressIndex >= 0);
  assert.deepEqual(i95.geometry.coordinates[expressIndex][0], [-77.1440825, 38.8132433]);
  assert.ok(!i95.properties.osm_way_ids.includes(50658205));
  assert.ok(!dulles.properties.osm_way_ids.includes(8801478));
  assert.ok(!dulles.properties.osm_way_ids.includes(8799377));
  assert.ok(i66.geometry.coordinates.flat().every(([longitude]) => longitude > -77.225),
    "I-66 coverage remains inside the Beltway");
});

test("Van Dorn TP1 anchors to OSM access geometry, separately from the express mainline", () => {
  const access = routeData.features.find(({ properties }) => properties.role === "access");
  const i495 = routeData.features.find(({ properties }) => (
    properties.facility === "i495" && properties.role === "mainline"
  ));
  assert.ok(access);
  assert.ok(i495);
  assert.equal(access.properties.facility, "i495");
  assert.ok(access.geometry.coordinates.flat().some((coordinate) => (
    coordinate[0] === tp1Coordinates[0] && coordinate[1] === tp1Coordinates[1]
  )));
  assert.ok(i495.geometry.coordinates.flat().every(([longitude]) => longitude < -77.18),
    "ordinary Beltway lanes toward Van Dorn must not be shown as express lanes");
});

test("coverage points snap onto their own roads within 500m while airports and source data stay fixed", async () => {
  const snapshot = commuteMap.validateCoverageLocations(JSON.parse(await readFile(
    new URL("../agent/assets/coverage-locations.json", import.meta.url), "utf8",
  )));
  const original = structuredClone(snapshot);
  let moved = 0;
  for (const location of snapshot.locations) {
    const coordinate = commuteMap.coverageCoordinates(location);
    if (location.points.some(({ role }) => role === "airport")) {
      assert.equal(coordinate, location.coordinates);
      continue;
    }
    const [longitude, latitude] = coordinate;
    const delta = Math.hypot(
      (longitude - location.coordinates[0]) * 111_320 * Math.cos(latitude * Math.PI / 180),
      (latitude - location.coordinates[1]) * 111_320,
    );
    assert.ok(delta <= 501, `${location.points[0].point_id} moved ${delta}m`);
    const tysonsFeeder = location.points.some(({ point_id: pointId }) => pointId.startsWith("i66:7:"));
    if (tysonsFeeder) assert.ok(delta > 0.001 && delta < 5,
      "VDOT's SR267 feeder point stays near Tysons on eastbound Dulles mainline way 38081414");
    if (delta < 0.001) continue;
    moved++;
    const movements = new Set(location.points.map(({ facility, point_id: pointId, direction, role }) => (
      `${facility === "dtr" || pointId.startsWith("i66:7:") ? "dulles" : facility}:${direction}:${role}`
    )));
    const lines = routeData.features.flatMap(({ properties, geometry }) => geometry.coordinates.filter((_, index) => (
      properties.way_movements[index].some((movement) => movements.has(movement))
      && (!tysonsFeeder || properties.osm_way_ids[index] === 38081414)
    )));
    assert.ok(lines.some((line) => pointOnLine(coordinate, line)),
      `${location.points[0].point_id} must land on geometry for its facility, direction and access role`);
  }
  assert.ok(moved >= 4, "road points should actually move onto the OSM geometry");
  assert.deepEqual(snapshot, original, "snapping must not change the oracle snapshot");
});

test("GW Parkway southbound entrance cannot snap to a nearby northbound or general-lane exit", async () => {
  const ways = new Map(routeData.features.flatMap(({ properties, geometry }) => properties.osm_way_ids.map((id, index) => (
    /** @type {[number, {coordinates: number[][], movements: string[]}]} */ ([id, {
      coordinates: geometry.coordinates[index], movements: properties.way_movements[index],
    }])
  ))));
  for (const id of [124083385, 537602766, 882176401, 882176402, 882176403]) {
    assert.ok(!ways.has(id), `unrelated ramp ${id} is not part of the supported overlay`);
  }
  const entry = ways.get(1448086167);
  const approach = ways.get(26707566);
  const exit = ways.get(26707564);
  assert.ok(entry && approach && exit);
  assert.ok(entry.movements.includes("i495:SB:entry"));
  assert.ok(!entry.movements.includes("i495:NB:exit"));
  assert.deepEqual(approach.movements, ["i495:SB:entry"]);
  assert.ok(exit.movements.includes("i495:NB:exit"));
  assert.ok(!exit.movements.includes("i495:SB:entry"));
  const snapshot = commuteMap.validateCoverageLocations(JSON.parse(await readFile(
    new URL("../agent/assets/coverage-locations.json", import.meta.url), "utf8",
  )));
  const location = snapshot.locations.find(({ points }) => points.some(({ point_id: pointId }) => pointId === "i495:180SO"));
  assert.ok(location);
  // OSM node 292441942 is the closest point of the verified southbound entry.
  assert.deepEqual(entry.coordinates[0], [-77.1835471, 38.9638971]);
  assert.deepEqual(approach.coordinates.at(-1), entry.coordinates[0]);
  const coordinate = commuteMap.coverageCoordinates(location);
  assert.ok(pointOnLine(coordinate, approach.coordinates), "pin stays on the approach entering southbound express lanes");
  assert.ok(!pointOnLine(coordinate, exit.coordinates), "the nearer northbound exit is ineligible");
});

test("mainline snapping respects travel direction and preserves points without a nearby eligible road", async () => {
  const snapshot = commuteMap.validateCoverageLocations(JSON.parse(await readFile(
    new URL("../agent/assets/coverage-locations.json", import.meta.url), "utf8",
  )));
  const location = snapshot.locations.find(({ points }) => points.some(({ point_id: pointId }) => pointId === "i66:17:entry:WB"));
  const i66 = routeData.features.find(({ properties }) => properties.facility === "i66" && properties.role === "mainline");
  assert.ok(location && i66);
  const westbound = i66.properties.osm_way_ids.indexOf(1552305099);
  const eastbound = i66.properties.osm_way_ids.indexOf(1552305101);
  assert.ok(westbound >= 0 && eastbound >= 0);
  assert.deepEqual(i66.properties.way_movements[westbound], ["i66:WB:entry", "i66:WB:exit"]);
  assert.deepEqual(i66.properties.way_movements[eastbound], ["i66:EB:entry", "i66:EB:exit"]);
  const coordinate = commuteMap.coverageCoordinates(location);
  assert.ok(pointOnLine(coordinate, i66.geometry.coordinates[westbound]));
  assert.ok(!pointOnLine(coordinate, i66.geometry.coordinates[eastbound]),
    "the nearly coincident eastbound carriageway must not capture a westbound entrance");
  const northbound = {
    coordinates: [-77.48001, 38.345],
    points: [{ point_id: "test:northbound-entry", facility: "i95", direction: "NB", role: "entry", label: "Northbound entrance" }],
  };
  const originalFeatures = routeData.features;
  const southbound = structuredClone(i66);
  southbound.properties.facility = "i95";
  southbound.properties.osm_way_ids = [1];
  southbound.properties.way_movements = [["i95:SB:exit"]];
  southbound.geometry.coordinates = [[[-77.48, 38.35], [-77.48, 38.34]]];
  try {
    routeData.features = [southbound];
    assert.equal(commuteMap.coverageCoordinates(northbound), northbound.coordinates,
      "a southbound exit one meter away must not capture a northbound entrance without eligible geometry");
  } finally {
    routeData.features = originalFeatures;
  }
});

test("I-95 reversible lanes preserve actual ramp movements and the Route 17 northbound approach", async () => {
  const expected = new Map([
    [40253505, ["i95:NB:entry"]],
    [40253503, ["i95:NB:entry", "i95:SB:exit"]],
    [636701122, ["i95:NB:exit", "i95:SB:entry"]],
    [1020591635, ["i95:NB:entry"]],
  ]);
  for (const [id, movements] of expected) {
    const feature = routeData.features.find(({ properties }) => properties.osm_way_ids.includes(id));
    assert.ok(feature, `verified I-95 way ${id} is present`);
    const index = feature.properties.osm_way_ids.indexOf(id);
    assert.deepEqual(feature.properties.way_movements[index], movements,
      `reversible mainlines must not make one-way ramp ${id} eligible in both directions`);
  }
  const access = routeData.features.find(({ properties }) => properties.osm_way_ids.includes(1020591635));
  assert.ok(access);
  assert.equal(access.properties.role, "access", "the ordinary approach is not express mainline");
  const snapshot = commuteMap.validateCoverageLocations(JSON.parse(await readFile(
    new URL("../agent/assets/coverage-locations.json", import.meta.url), "utf8",
  )));
  const location = snapshot.locations.find(({ points }) => points.some(({ point_id: pointId }) => pointId === "i95:234NO"));
  assert.ok(location);
  const coordinate = commuteMap.coverageCoordinates(location);
  assert.notDeepEqual(coordinate, location.coordinates, "Route 17 northbound access now has verified road geometry");
  assert.ok(pointOnLine(coordinate, access.geometry.coordinates[access.properties.osm_way_ids.indexOf(1020591635)]));
  assert.ok(Math.hypot(
    (coordinate[0] - location.coordinates[0]) * 111320 * Math.cos(coordinate[1] * Math.PI / 180),
    (coordinate[1] - location.coordinates[1]) * 111320,
  ) < 2,
    "Route 17 follows its northbound approach within two meters of the source point");
});

test("Springfield ramps connect I-95 and I-495 through shared OSM vertices", () => {
  const from = [-77.1721104, 38.7945089]; // OSM node 6003858541 on I-95 / I-395.
  const to = [-77.207989, 38.8007188]; // OSM node 64056097 on I-495 Express.
  for (const [facility, coordinate] of /** @type {[string, number[]][]} */ ([["i95", from], ["i495", to]])) {
    const mainline = routeData.features.find(({ properties }) => (
      properties.facility === facility && properties.role === "mainline"
    ));
    assert.ok(mainline?.geometry.coordinates.flat().some((point) => point.join(",") === coordinate.join(",")));
  }
  const ways = new Map(routeData.features.filter(({ properties }) => properties.role !== "mainline")
    .flatMap(({ properties, geometry }) => properties.osm_way_ids.map((id, index) => (
      /** @type {[number, number[][]]} */ ([id, geometry.coordinates[index]])
    ))));
  let endpoint = from.join(",");
  for (const id of [
    191328199, 191326103, 636701123, 159458266, 159458265, 191328237, 636701113,
    636701112, 696525976, 696525975, 49037780, 636964660, 1071598926, 636964659,
    49037781, 469109797, 944264876, 469109796, 164130177, 696525962,
  ]) {
    const line = ways.get(id);
    assert.ok(line, `verified Springfield connection way ${id} is present`);
    const ends = [line[0].join(","), line[line.length - 1].join(",")];
    assert.ok(ends.includes(endpoint), `way ${id} shares its connecting vertex`);
    endpoint = ends[0] === endpoint ? ends[1] : ends[0];
  }
  assert.equal(endpoint, to.join(","));
});
