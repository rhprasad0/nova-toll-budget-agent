/** @typedef {typeof import("./commute-estimates.json")} EstimateSnapshot */
/** @typedef {EstimateSnapshot['estimates'][number]} Estimate */
/** @typedef {{schema_version: number, locations: {coordinates: number[], points: {point_id: string, facility: string, label: string, direction: string | null, role: string}[]}[]}} CoverageSnapshot */
/** @typedef {CoverageSnapshot['locations'][number]} Location */
import { routeData, tp1Coordinates } from "./commute-routes.mjs";

const EXPECTED_IDS = ["dumfries", "springfield-franconia", "leesburg", "i66-west"];
const MONEY = /^(?:0|[1-9][0-9]{0,8})[.][0-9]{2}$/;
const MAP_BOUNDS = [[-77.61, 38.28], [-77.01, 39.15]];
const MAP_PADDING = { top: 72, right: 48, bottom: 32, left: 48 };
const COLORS = {
  i66: "#3f79aa",
  i95: "#087f83",
  i495: "#ad7d35",
  dulles: "#428568",
  greenway: "#8072a3",
};
const CORRIDOR_LABELS = ["I-66", "I-95 / 395", "I-495", "Dulles Toll Road", "Greenway"];
const ACCESS_COLOR = "#63736d";
const COVERAGE_FACILITIES = new Set(["i66", "i95", "i495", "dtr", "greenway", "airport_iad", "airport_dca"]);
const COVERAGE_DIRECTIONS = new Set(["NB", "SB", "EB", "WB"]);
/** @type {Record<string, string>} */
const DIRECTION_NAMES = {
  NB: "Northbound",
  SB: "Southbound",
  EB: "Eastbound",
  WB: "Westbound",
};
const TP1_POINT_IDS = new Set(["i495:192NO", "i495:192SD"]);
const invalid = () => {
  throw new Error("invalid commute estimate snapshot");
};

const invalidCoverage = () => {
  throw new Error("invalid coverage location snapshot");
};

/** @param {Estimate["outbound"]} trip */
const validTrip = (trip) => trip && typeof trip === "object"
  && typeof trip.origin_point_id === "string" && trip.origin_point_id
  && typeof trip.destination_point_id === "string" && trip.destination_point_id;

/** @param {unknown} input @returns {EstimateSnapshot} */
export function validateEstimateSnapshot(input) {
  // The existing checks below validate the external JSON before it is returned.
  const snapshot = /** @type {EstimateSnapshot} */ (input);
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
          (name) => !MONEY.test(scenarios[/** @type {keyof typeof scenarios} */ (name)]?.annual_toll_usd),
        )
        || Number(scenarios.p25.annual_toll_usd) > Number(scenarios.p50.annual_toll_usd)
        || Number(scenarios.p50.annual_toll_usd) > Number(scenarios.p90.annual_toll_usd);
    })) invalid();
  return snapshot;
}

/** @param {unknown} input @returns {CoverageSnapshot} */
export function validateCoverageLocations(input) {
  const snapshot = /** @type {CoverageSnapshot} */ (input);
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
        || (airport ? point.direction !== null : !COVERAGE_DIRECTIONS.has(/** @type {string} */ (point.direction)))
        || airport !== point.facility.startsWith("airport_")) invalidCoverage();
      pointsSeen.add(point.point_id);
    }
  }
  return snapshot;
}

/** @param {Location} location */
const isTp1 = (location) => location.points.length === TP1_POINT_IDS.size
  && location.points.every(({ point_id: pointId }) => TP1_POINT_IDS.has(pointId));

/** @param {Location} location */
export function coverageCoordinates(location) {
  if (isTp1(location)) return tp1Coordinates;
  if (location.points.some(({ role }) => role === "airport")) return location.coordinates;
  // I-66 point 7 is the modeled Route 123 feeder on the Dulles Connector Road.
  const movements = new Set(location.points.map(({ facility, direction, role, point_id: pointId }) => (
    `${facility === "dtr" || pointId.startsWith("i66:7:") ? "dulles" : facility}:${direction}:${role}`
  )));
  const [longitude, latitude] = location.coordinates;
  // Local meter projection is sufficient for this regional, 500 m display adjustment.
  const xScale = 111320 * Math.cos(latitude * Math.PI / 180);
  let nearest = location.coordinates;
  let distanceSquared = 500 ** 2;
  for (const { properties, geometry } of routeData.features) {
    for (let lineIndex = 0; lineIndex < geometry.coordinates.length; lineIndex++) {
      if (!properties.way_movements[lineIndex].some((movement) => movements.has(movement))) continue;
      const line = geometry.coordinates[lineIndex];
      for (let index = 1; index < line.length; index++) {
        const start = line[index - 1];
        const end = line[index];
        const x = (start[0] - longitude) * xScale;
        const y = (start[1] - latitude) * 111320;
        const dx = (end[0] - start[0]) * xScale;
        const dy = (end[1] - start[1]) * 111320;
        const lengthSquared = dx * dx + dy * dy;
        const fraction = lengthSquared ? Math.max(0, Math.min(1, -(x * dx + y * dy) / lengthSquared)) : 0;
        const distance = (x + fraction * dx) ** 2 + (y + fraction * dy) ** 2;
        if (distance < distanceSquared) {
          distanceSquared = distance;
          nearest = [start[0] + fraction * (end[0] - start[0]), start[1] + fraction * (end[1] - start[1])];
        }
      }
    }
  }
  return nearest;
}

/** @param {Location} location */
export function coverageDetail(location) {
  if (isTp1(location)) return {
    kicker: "Supported route point",
    title: "I-495/I-95 near Van Dorn Street",
    paragraphs: [
      "Northbound entrance · Southbound exit",
      "The dashed connection follows the Beltway approach to the express lanes.",
    ],
  };
  /** @type {Map<string, Set<string>>} */
  const names = new Map();
  for (const point of location.points) {
    const access = point.role === "airport"
      ? "Supported origin or destination"
      : `${DIRECTION_NAMES[/** @type {string} */ (point.direction)]} ${point.role === "entry" ? "entrance" : "exit"}`;
    if (!names.has(point.label)) names.set(point.label, new Set());
    /** @type {Set<string>} */ (names.get(point.label)).add(access);
  }
  const rows = [...names.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([label, accesses]) => [label, [...accesses].sort().join(" · ")]);
  return {
    kicker: "Supported route point",
    title: rows.length === 1 ? rows[0][0] : "Names at this location",
    paragraphs: rows.length === 1
      ? [rows[0][1]]
      : rows.map(([label, accesses]) => `${label}: ${accesses}`),
  };
}

/** @param {string | number} value */
export const formatAnnualToll = (value) => `${new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
}).format(Number(value))}/yr`;

/** @param {HTMLElement} detail @param {string} kicker @param {string} title @param {string[]} paragraphs */
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
  /** @type {HTMLElement} */ (document.querySelector("#map-loading")).hidden = true;
  /** @type {HTMLElement} */ (document.querySelector("#map-error")).hidden = false;
};

/** @param {Location} location @param {Record<string, string>} colors */
const markerColor = (location, colors) => {
  const facilities = new Set(location.points.map(({ facility }) => facility));
  return facilities.size === 1 ? colors[/** @type {string} */ (facilities.values().next().value)] : "#667985";
};

/** @param {ReturnType<typeof setTimeout>} [watchdog] */
export async function mountCommuteMap(watchdog = setTimeout(showError, 12000)) {
  const detail = /** @type {HTMLElement} */ (document.querySelector("#map-detail"));
  const reset = /** @type {HTMLButtonElement} */ (document.querySelector("#reset-map"));
  reset.disabled = true;
  try {
    const theme = getComputedStyle(document.documentElement);
    const colors = Object.fromEntries(Object.entries(COLORS).map(([key, fallback]) => [
      key, theme.getPropertyValue(`--route-${key}`).trim() || fallback,
    ]));
    const coverageColors = { ...colors, dtr: colors.dulles, airport_iad: "#326387", airport_dca: "#326387" };
    const legend = document.querySelector("#map-legend");
    legend?.replaceChildren(...[...Object.values(colors), ACCESS_COLOR].map((color, index) => {
      const item = document.createElement("span");
      const swatch = document.createElement("span");
      item.className = "map-legend-item";
      item.setAttribute("role", "listitem");
      swatch.className = "map-legend-swatch";
      if (index === CORRIDOR_LABELS.length) swatch.classList.add("map-legend-access");
      swatch.style.setProperty("--corridor-color", color);
      swatch.setAttribute("aria-hidden", "true");
      item.append(swatch, CORRIDOR_LABELS[index] || "Access connection");
      return item;
    }));
    const [estimateResponse, coverageResponse] = await Promise.all([
      fetch("/assets/commute-estimates.json", { cache: "no-store" }),
      fetch("/assets/coverage-locations.json", { cache: "no-store" }),
    ]);
    if (!estimateResponse.ok || !coverageResponse.ok) throw new Error("map data unavailable");
    const snapshot = validateEstimateSnapshot(await estimateResponse.json());
    const coverage = validateCoverageLocations(await coverageResponse.json());
    const snapshotDate = `Estimate snapshot generated ${new Date(snapshot.generated_at).toLocaleDateString("en-US", { dateStyle: "medium" })}.`;
    const showGuide = () => setDetail(detail, "Map guide", "Select a commute, entrance, or exit", [
      "Large pins show historical P50 annual toll estimates for commutes to Washington.",
      "Small pins show the place names and directions TollChat supports in route questions.",
      "Zoom in to see entrance ramps and interchange connections.",
      "Dashed lines show access connections to the toll corridors.",
      snapshotDate,
    ]);
    showGuide();
    const maplibregl = await import("./maplibre-gl-6.0.0/maplibre-gl.mjs");
    const map = new maplibregl.Map({
      container: "commute-map",
      style: "https://tiles.openfreemap.org/styles/positron",
      bounds: MAP_BOUNDS,
      fitBoundsOptions: { padding: MAP_PADDING, duration: 0 },
      cooperativeGestures: true,
      dragRotate: false,
      attributionControl: false,
    });
    map.touchPitch.disable();
    map.keyboard.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({
      // The basemap includes this same credit; MapLibre deduplicates it.
      customAttribution: 'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>',
      compact: true,
    }), "bottom-right");

    let ready = false;
    /** @type {HTMLElement | undefined} */
    let selected;
    const clearSelection = () => {
      selected?.removeAttribute("data-selected");
      selected = undefined;
    };
    /** @param {HTMLElement} marker */
    const selectMarker = (marker) => {
      clearSelection();
      selected = marker;
      marker.dataset.selected = "true";
    };
    /** @param {Estimate} estimate @param {HTMLElement} marker */
    const selectEstimate = (estimate, marker) => {
      selectMarker(marker);
      const { scenarios, coverage: evidence } = estimate;
      setDetail(detail, "Historical annual estimate", `${estimate.label} → Washington, DC`, [
        `P25 ${formatAnnualToll(scenarios.p25.annual_toll_usd)} · P50 ${formatAnnualToll(scenarios.p50.annual_toll_usd)} · P90 ${formatAnnualToll(scenarios.p90.annual_toll_usd)}`,
        `${evidence.complete_pair_count} of ${evidence.eligible_date_count} eligible recent weekdays had complete round-trip evidence (${evidence.coverage_percent}% coverage).`,
        "Tolls only · 2-axle E-ZPass vehicle · 240 commute days · 8:30 AM outbound / 5:30 PM return. This historical estimate is not a forecast or an operator quote.",
        snapshotDate,
      ]);
    };
    /** @param {Location} location @param {HTMLElement} marker */
    const selectCoverage = (location, marker) => {
      selectMarker(marker);
      const selectedDetail = coverageDetail(location);
      setDetail(detail, selectedDetail.kicker, selectedDetail.title, selectedDetail.paragraphs);
    };

    reset.addEventListener("click", () => {
      clearSelection();
      showGuide();
      map.resize();
      map.fitBounds(MAP_BOUNDS, {
        padding: MAP_PADDING,
        duration: globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? 0 : 450,
      });
    });

    map.on("load", () => {
      map.addSource("toll-corridors", { type: "geojson", data: routeData });
      map.addLayer({
        id: "toll-corridor-casing",
        type: "line",
        source: "toll-corridors",
        filter: ["==", ["get", "role"], "mainline"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 8, "line-opacity": 0.95 },
      });
      map.addLayer({
        id: "toll-corridors",
        type: "line",
        source: "toll-corridors",
        filter: ["==", ["get", "role"], "mainline"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["match", ["get", "facility"], ...Object.entries(colors).flat(), colors.i66],
          "line-width": 4,
          "line-opacity": 0.9,
        },
      });

      map.addLayer({
        id: "toll-access-connections",
        type: "line",
        source: "toll-corridors",
        filter: ["==", ["get", "role"], "access"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ACCESS_COLOR,
          "line-width": 3,
          "line-dasharray": [2, 2],
        },
      });

      map.addLayer({
        id: "toll-ramp-casing",
        type: "line",
        source: "toll-corridors",
        minzoom: 10,
        filter: ["==", ["get", "role"], "ramp"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#ffffff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 3, 13, 5, 16, 7],
          "line-opacity": 0.95,
        },
      });
      map.addLayer({
        id: "toll-ramps",
        type: "line",
        source: "toll-corridors",
        minzoom: 10,
        filter: ["==", ["get", "role"], "ramp"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["match", ["get", "facility"], ...Object.entries(colors).flat(), ACCESS_COLOR],
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 13, 2, 16, 3.5],
          "line-opacity": 0.95,
        },
      });

      for (const location of coverage.locations) {
        const marker = document.createElement("button");
        const markerDetail = coverageDetail(location);
        marker.className = "coverage-marker";
        marker.type = "button";
        marker.style.setProperty("--coverage-color", markerColor(location, coverageColors));
        if (location.points.some(({ role }) => role === "airport")) marker.dataset.airport = "true";
        marker.setAttribute(
          "aria-label",
          `${markerDetail.title}. ${markerDetail.paragraphs.join(". ")}`,
        );
        marker.addEventListener("click", () => selectCoverage(location, marker));
        marker.addEventListener("focus", () => selectCoverage(location, marker));
        new maplibregl.Marker({ element: marker, anchor: "center" })
          .setLngLat(coverageCoordinates(location))
          .addTo(map);
      }

      for (const estimate of snapshot.estimates) {
        const origin = coverage.locations.find(({ points }) => points.some(
          ({ point_id: pointId }) => pointId === estimate.outbound.origin_point_id,
        ));
        const pin = document.createElement("button");
        const marker = document.createElement("span");
        const place = document.createElement("span");
        const price = document.createElement("strong");
        pin.className = "estimate-pin";
        const below = estimate.id === "springfield-franconia" || estimate.id === "dumfries";
        if (below) pin.dataset.orientation = "below";
        pin.type = "button";
        pin.setAttribute("aria-label", `${estimate.label}: P50 annual toll ${formatAnnualToll(estimate.scenarios.p50.annual_toll_usd)} to Washington, DC`);
        marker.className = "estimate-marker";
        place.textContent = estimate.label;
        price.textContent = formatAnnualToll(estimate.scenarios.p50.annual_toll_usd);
        marker.append(place, price);
        pin.append(marker);
        pin.addEventListener("click", () => selectEstimate(estimate, pin));
        pin.addEventListener("focus", () => selectEstimate(estimate, pin));
        new maplibregl.Marker({ element: pin, anchor: below ? "top" : "bottom" })
          .setLngLat(origin ? coverageCoordinates(origin) : estimate.coordinates)
          .addTo(map);
      }

      const destination = document.createElement("div");
      destination.className = "destination-marker";
      destination.textContent = "DC";
      destination.setAttribute("aria-label", "Washington, DC destination");
      new maplibregl.Marker({ element: destination, anchor: "center" })
        .setLngLat([-77.0369, 38.9072])
        .addTo(map);
      /** @type {HTMLElement} */ (document.querySelector("#map-loading")).hidden = true;
      /** @type {HTMLElement} */ (document.querySelector("#map-error")).hidden = true;
      reset.disabled = false;
      ready = true;
      clearTimeout(watchdog);
    });
    map.on("error", (event) => {
      if (!ready) {
        clearTimeout(watchdog);
        showError();
      }
      console.error("TollChat map failed", event.error);
    });
    return map;
  } catch (error) {
    clearTimeout(watchdog);
    showError();
    throw error;
  }
}
