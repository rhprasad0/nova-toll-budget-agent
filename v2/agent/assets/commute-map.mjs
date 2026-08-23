import { routeData } from "./commute-routes.mjs";

const EXPECTED_IDS = ["dumfries", "springfield-franconia", "leesburg", "i66-west"];
const MONEY = /^(?:0|[1-9][0-9]{0,8})[.][0-9]{2}$/;
const MAP_BOUNDS = [[-77.61, 38.28], [-77.01, 39.15]];
const COLORS = {
  i66: "#24a8f2",
  i95: "#f47735",
  i495: "#f4c430",
  dulles: "#51d49b",
  greenway: "#8e6ad8",
};
const COVERAGE_COLORS = {
  i66: COLORS.i66,
  i95: COLORS.i95,
  i495: COLORS.i495,
  dtr: COLORS.dulles,
  greenway: COLORS.greenway,
  airport_iad: "#8bd4ff",
  airport_dca: "#8bd4ff",
};
const COVERAGE_FACILITIES = new Set(Object.keys(COVERAGE_COLORS));
const COVERAGE_DIRECTIONS = new Set(["NB", "SB", "EB", "WB"]);
const DIRECTION_NAMES = {
  NB: "Northbound",
  SB: "Southbound",
  EB: "Eastbound",
  WB: "Westbound",
};
// Census TIGER/Line 2019 I-495 LINEARID 1106220849438, from the v1 trim to TP1.
const TP1_CONNECTOR = [
  [-77.205634, 38.799923], [-77.205254, 38.799834], [-77.196633, 38.797845],
  [-77.196032, 38.797707], [-77.194412, 38.797333], [-77.193925, 38.797214],
  [-77.193856, 38.797198], [-77.193789, 38.797181], [-77.193345, 38.797073],
  [-77.192065, 38.796777], [-77.191757, 38.796709], [-77.190516, 38.796436],
  [-77.190389, 38.796408], [-77.189607, 38.796212], [-77.188871, 38.79601],
  [-77.188272, 38.795836], [-77.18737, 38.795553], [-77.186449, 38.795244],
  [-77.186133, 38.795167], [-77.185731, 38.795048], [-77.185344, 38.79493],
  [-77.184416, 38.794607], [-77.183988, 38.79444], [-77.18385, 38.794384],
  [-77.183718, 38.794332], [-77.183439, 38.794239], [-77.1829, 38.79402],
  [-77.182581, 38.793887], [-77.181571, 38.793481], [-77.181085, 38.793282],
  [-77.18034, 38.793023], [-77.179629, 38.792803], [-77.17904, 38.792676],
  [-77.178869, 38.792627], [-77.178253, 38.792467], [-77.177854, 38.79238],
  [-77.177594, 38.79232], [-77.177357, 38.792267], [-77.177307, 38.792257],
  [-77.176569, 38.792131], [-77.176078, 38.792058], [-77.175781, 38.792009],
  [-77.175575, 38.791978], [-77.175415, 38.791947], [-77.175279, 38.791924],
  [-77.175063, 38.791891], [-77.17453, 38.791828], [-77.174405, 38.791813],
  [-77.174159, 38.791788], [-77.173073, 38.791643], [-77.172321, 38.791555],
  [-77.172211, 38.791541], [-77.17197, 38.791516], [-77.171812, 38.791499],
  [-77.171565, 38.791482], [-77.171001, 38.791444], [-77.170402, 38.791415],
  [-77.170294, 38.79141], [-77.170108, 38.791404], [-77.16999, 38.7914],
  [-77.169247, 38.791374], [-77.168646, 38.791361], [-77.166796, 38.791422],
  [-77.166366, 38.791438], [-77.166018, 38.791453], [-77.165689, 38.791467],
  [-77.165196, 38.791499], [-77.164711, 38.791542], [-77.164455, 38.791568],
  [-77.163853, 38.791634], [-77.162999, 38.791747], [-77.162744, 38.791792],
  [-77.162229, 38.791883], [-77.161938, 38.79194], [-77.160691, 38.792184],
  [-77.159398, 38.792463], [-77.157902, 38.792829], [-77.156391, 38.793131],
  [-77.1554, 38.793337], [-77.154988, 38.793412], [-77.154738, 38.793466],
  [-77.154508, 38.793504],
];
routeData.features.find(({ properties }) => properties.facility === "i495")
  .geometry.coordinates.push(TP1_CONNECTOR);

const invalid = () => {
  throw new Error("invalid commute estimate snapshot");
};

const invalidCoverage = () => {
  throw new Error("invalid coverage location snapshot");
};

const validTrip = (trip) => trip && typeof trip === "object"
  && typeof trip.origin_point_id === "string" && trip.origin_point_id
  && typeof trip.destination_point_id === "string" && trip.destination_point_id;

export function validateEstimateSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object" || snapshot.schema_version !== 1
    || snapshot.destination !== "Washington, DC" || !Number.isFinite(Date.parse(snapshot.generated_at))
    || !snapshot.assumptions || snapshot.assumptions.planned_annual_commute_days !== 240
    || snapshot.assumptions.outbound_departure_time !== "08:30:00"
    || snapshot.assumptions.return_departure_time !== "17:30:00"
    || !Array.isArray(snapshot.estimates) || snapshot.estimates.length !== EXPECTED_IDS.length
    || snapshot.estimates.some((estimate, index) => {
      const scenarios = estimate?.scenarios;
      const coordinates = estimate?.coordinates;
      const coverage = estimate?.coverage;
      return estimate?.id !== EXPECTED_IDS[index] || typeof estimate.label !== "string"
        || !Array.isArray(coordinates) || coordinates.length !== 2
        || coordinates.some((coordinate) => !Number.isFinite(coordinate))
        || coordinates[0] < -180 || coordinates[0] > 180
        || coordinates[1] < -90 || coordinates[1] > 90
        || !validTrip(estimate.outbound) || !validTrip(estimate.return)
        || !coverage || !Number.isInteger(coverage.eligible_date_count)
        || !Number.isInteger(coverage.complete_pair_count)
        || typeof coverage.coverage_percent !== "string"
        || !scenarios || ["p25", "p50", "p90"].some(
          (name) => !MONEY.test(scenarios[name]?.annual_toll_usd),
        )
        || Number(scenarios.p25.annual_toll_usd) > Number(scenarios.p50.annual_toll_usd)
        || Number(scenarios.p50.annual_toll_usd) > Number(scenarios.p90.annual_toll_usd);
    })) invalid();
  return snapshot;
}

export function validateCoverageLocations(snapshot) {
  if (!snapshot || typeof snapshot !== "object" || snapshot.schema_version !== 1
    || !Array.isArray(snapshot.locations) || !snapshot.locations.length
    || snapshot.locations.length > 500) invalidCoverage();
  const coordinatesSeen = new Set();
  const pointsSeen = new Set();
  for (const location of snapshot.locations) {
    const coordinates = location?.coordinates;
    if (!Array.isArray(coordinates) || coordinates.length !== 2
      || coordinates.some((coordinate) => !Number.isFinite(coordinate))
      || coordinates[0] < -180 || coordinates[0] > 180
      || coordinates[1] < -90 || coordinates[1] > 90
      || !Array.isArray(location.points) || !location.points.length) invalidCoverage();
    const coordinateKey = coordinates.join(",");
    if (coordinatesSeen.has(coordinateKey)) invalidCoverage();
    coordinatesSeen.add(coordinateKey);
    for (const point of location.points) {
      const airport = point?.role === "airport";
      if (!point || typeof point !== "object"
        || typeof point.point_id !== "string" || !point.point_id || point.point_id.length > 128
        || pointsSeen.has(point.point_id) || !COVERAGE_FACILITIES.has(point.facility)
        || typeof point.label !== "string" || !point.label || point.label.length > 200
        || !["entry", "exit", "airport"].includes(point.role)
        || (airport ? point.direction !== null : !COVERAGE_DIRECTIONS.has(point.direction))
        || airport !== point.facility.startsWith("airport_")) invalidCoverage();
      pointsSeen.add(point.point_id);
    }
  }
  return snapshot;
}

export function coverageDetail(location) {
  const names = new Map();
  for (const point of location.points) {
    const access = point.role === "airport"
      ? "Supported origin or destination"
      : `${DIRECTION_NAMES[point.direction]} ${point.role === "entry" ? "entrance" : "exit"}`;
    if (!names.has(point.label)) names.set(point.label, new Set());
    names.get(point.label).add(access);
  }
  const rows = [...names.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([label, accesses]) => [label, [...accesses].sort().join(" · ")]);
  return {
    kicker: "Supported access",
    title: rows.length === 1 ? rows[0][0] : "Names at this location",
    paragraphs: rows.length === 1
      ? [rows[0][1]]
      : rows.map(([label, accesses]) => `${label}: ${accesses}`),
  };
}

export const formatAnnualToll = (value) => `${new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
}).format(Number(value))}/yr`;

const setDetail = (detail, kicker, title, paragraphs) => {
  const tag = document.createElement("span");
  const heading = document.createElement("strong");
  tag.className = "map-detail-kicker";
  tag.textContent = kicker;
  heading.textContent = title;
  detail.replaceChildren(tag, heading, ...paragraphs.map((text) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    return paragraph;
  }));
};

const showError = () => {
  document.querySelector("#map-loading").hidden = true;
  document.querySelector("#map-error").hidden = false;
};

const markerColor = (location) => {
  const facilities = new Set(location.points.map(({ facility }) => facility));
  return facilities.size === 1 ? COVERAGE_COLORS[facilities.values().next().value] : "#ffffff";
};

export async function mountCommuteMap() {
  const detail = document.querySelector("#map-detail");
  const reset = document.querySelector("#reset-map");
  reset.disabled = true;
  const [estimateResponse, coverageResponse] = await Promise.all([
    fetch("/assets/commute-estimates.json", { cache: "no-store" }),
    fetch("/assets/coverage-locations.json", { cache: "no-store" }),
  ]);
  if (!estimateResponse.ok || !coverageResponse.ok) throw new Error("map data unavailable");
  const snapshot = validateEstimateSnapshot(await estimateResponse.json());
  const coverage = validateCoverageLocations(await coverageResponse.json());
  const maplibregl = await import("./maplibre-gl-6.0.0/maplibre-gl.mjs");
  const map = new maplibregl.Map({
    container: "commute-map",
    style: "https://tiles.openfreemap.org/styles/dark",
    bounds: MAP_BOUNDS,
    fitBoundsOptions: { padding: 48, duration: 0 },
    maxBounds: [[-78.05, 38.05], [-76.7, 39.42]],
    cooperativeGestures: true,
    dragRotate: false,
    attributionControl: false,
  });
  map.touchPitch.disable();
  map.keyboard.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.AttributionControl({
    customAttribution: "Basemap © OpenStreetMap contributors · Corridors: U.S. Census Bureau TIGER/Line 2019",
    compact: true,
  }), "bottom-right");

  let ready = false;
  let selected;
  const clearSelection = () => {
    selected?.removeAttribute("data-selected");
    selected = undefined;
  };
  const selectMarker = (marker) => {
    clearSelection();
    selected = marker;
    marker.dataset.selected = "true";
  };
  const showGuide = () => setDetail(detail, "Map guide", "Choose a commute or entry/exit pin", [
    "Large pins show historical P50 annual toll ballparks to Washington.",
    "Small pins show the names and directions TollChat supports for route questions.",
    `Estimate snapshot generated ${new Date(snapshot.generated_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}.`,
  ]);
  const selectEstimate = (estimate, marker) => {
    selectMarker(marker);
    const { scenarios, coverage: evidence } = estimate;
    setDetail(detail, "Annual toll ballpark", `${estimate.label} → Washington, DC`, [
      `P25 ${formatAnnualToll(scenarios.p25.annual_toll_usd)} · P50 ${formatAnnualToll(scenarios.p50.annual_toll_usd)} · P90 ${formatAnnualToll(scenarios.p90.annual_toll_usd)}`,
      `${evidence.complete_pair_count} of ${evidence.eligible_date_count} eligible recent weekdays had complete round-trip evidence (${evidence.coverage_percent}% coverage).`,
      "Tolls only. Two-axle E-ZPass, 240 commute days; historical ballpark, not a forecast or operator quote.",
    ]);
  };
  const selectCoverage = (location, marker) => {
    selectMarker(marker);
    const selectedDetail = coverageDetail(location);
    setDetail(detail, selectedDetail.kicker, selectedDetail.title, selectedDetail.paragraphs);
  };

  reset.addEventListener("click", () => {
    clearSelection();
    showGuide();
    map.fitBounds(MAP_BOUNDS, {
      padding: 48,
      duration: globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? 0 : 450,
    });
  });

  map.on("load", () => {
    ready = true;
    map.addSource("toll-corridors", { type: "geojson", data: routeData });
    map.addLayer({
      id: "toll-corridor-casing",
      type: "line",
      source: "toll-corridors",
      paint: { "line-color": "#07142f", "line-width": 8, "line-opacity": 0.78 },
    });
    map.addLayer({
      id: "toll-corridors",
      type: "line",
      source: "toll-corridors",
      paint: {
        "line-color": ["match", ["get", "facility"], ...Object.entries(COLORS).flat(), "#24a8f2"],
        "line-width": 4,
        "line-opacity": 0.9,
      },
    });

    for (const location of coverage.locations) {
      const marker = document.createElement("button");
      const markerDetail = coverageDetail(location);
      marker.className = "coverage-marker";
      marker.type = "button";
      marker.style.setProperty("--coverage-color", markerColor(location));
      if (location.points.some(({ role }) => role === "airport")) marker.dataset.airport = "true";
      marker.setAttribute(
        "aria-label",
        `${markerDetail.title}. ${markerDetail.paragraphs.join(". ")}`,
      );
      marker.addEventListener("click", () => selectCoverage(location, marker));
      marker.addEventListener("focus", () => selectCoverage(location, marker));
      new maplibregl.Marker({ element: marker, anchor: "center" })
        .setLngLat(location.coordinates)
        .addTo(map);
    }

    for (const estimate of snapshot.estimates) {
      const marker = document.createElement("button");
      const place = document.createElement("span");
      const price = document.createElement("strong");
      marker.className = "estimate-marker";
      marker.type = "button";
      marker.setAttribute("aria-label", `${estimate.label}: P50 annual toll ${formatAnnualToll(estimate.scenarios.p50.annual_toll_usd)} to Washington, DC`);
      place.textContent = estimate.label;
      price.textContent = formatAnnualToll(estimate.scenarios.p50.annual_toll_usd);
      marker.append(place, price);
      marker.addEventListener("click", () => selectEstimate(estimate, marker));
      marker.addEventListener("focus", () => selectEstimate(estimate, marker));
      new maplibregl.Marker({ element: marker, anchor: "bottom" })
        .setLngLat(estimate.coordinates)
        .addTo(map);
    }

    const destination = document.createElement("div");
    destination.className = "destination-marker";
    destination.textContent = "DC";
    destination.setAttribute("aria-label", "Washington, DC destination");
    new maplibregl.Marker({ element: destination, anchor: "center" })
      .setLngLat([-77.0369, 38.9072])
      .addTo(map);
    document.querySelector("#map-loading").hidden = true;
    document.querySelector("#map-error").hidden = true;
    reset.disabled = false;
    showGuide();
  });
  map.on("error", (event) => {
    console.error("TollChat map failed", event.error);
  });
  setTimeout(() => {
    if (!ready) showError();
  }, 12000);
  return map;
}
