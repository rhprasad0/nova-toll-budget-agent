import { routeData } from "./commute-routes.mjs";

const EXPECTED_IDS = ["dumfries", "springfield-franconia", "leesburg", "i66-west"];
const MONEY = /^(?:0|[1-9][0-9]{0,8})[.][0-9]{2}$/;
const COLORS = {
  i66: "#24a8f2",
  i95: "#f47735",
  i495: "#f4c430",
  dulles: "#51d49b",
  greenway: "#8e6ad8",
};
const MARKER_OFFSETS = {
  "springfield-franconia": [45, 10],
  "i66-west": [-45, -10],
};

const invalid = () => {
  throw new Error("invalid commute estimate snapshot");
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

export async function mountCommuteMap() {
  const detail = document.querySelector("#map-detail");
  const response = await fetch("/assets/commute-estimates.json", { cache: "no-store" });
  if (!response.ok) throw new Error("commute estimates unavailable");
  const snapshot = validateEstimateSnapshot(await response.json());
  const maplibregl = await import("./maplibre-gl-6.0.0/maplibre-gl.mjs");
  const map = new maplibregl.Map({
    container: "commute-map",
    style: "https://tiles.openfreemap.org/styles/dark",
    bounds: [[-77.64, 38.49], [-76.98, 39.16]],
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
  const selectEstimate = (estimate, marker) => {
    selected?.removeAttribute("data-selected");
    selected = marker;
    marker.dataset.selected = "true";
    const { scenarios, coverage } = estimate;
    setDetail(detail, "Annual toll ballpark", `${estimate.label} → Washington, DC`, [
      `P25 ${formatAnnualToll(scenarios.p25.annual_toll_usd)} · P50 ${formatAnnualToll(scenarios.p50.annual_toll_usd)} · P90 ${formatAnnualToll(scenarios.p90.annual_toll_usd)}`,
      `${coverage.complete_pair_count} of ${coverage.eligible_date_count} eligible recent weekdays had complete round-trip evidence (${coverage.coverage_percent}% coverage).`,
      "Tolls only. Two-axle E-ZPass, 240 commute days; historical ballpark, not a forecast or operator quote.",
    ]);
  };

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
      new maplibregl.Marker({
        element: marker,
        anchor: "bottom",
        offset: MARKER_OFFSETS[estimate.id] ?? [0, 0],
      })
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
    setDetail(detail, "Fixed weekday schedule", "Choose an origin pin", [
      "P50 labels assume Monday–Friday trips leaving at 8:30 AM and returning at 5:30 PM for 240 commute days.",
      `Snapshot generated ${new Date(snapshot.generated_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}.`,
    ]);
  });
  map.on("error", (event) => {
    console.error("TollChat map failed", event.error);
  });
  setTimeout(() => {
    if (!ready) showError();
  }, 12000);
  return map;
}
