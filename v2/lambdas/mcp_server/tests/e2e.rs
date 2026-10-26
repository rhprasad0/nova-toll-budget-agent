//! End to end: the real router over HTTP and real MCP JSON-RPC, against the disposable oracle
//! database with its real catalog and least-privilege roles. Nothing is faked.
//! Run through `e2e.sh`, which starts the container.

use std::io::Write;
use std::sync::{Arc, Mutex, OnceLock};

use axum::Router;
use axum::http::header::CONTENT_TYPE;
use mcp_server::{App, Database, log_filter, router};
use serde_json::{Value, json};
use tokio::sync::{RwLock, RwLockReadGuard};
use tokio_postgres::NoTls;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

const DATABASE: &str = "nova_toll_mcp_e2e";

/// Lane state is global in the shared database: the test that changes it runs alone.
static LANES: RwLock<()> = RwLock::const_new(());

/// Public landmarks as (latitude, longitude). Reston and Tysons are Muse's own geocodes.
const RESTON_TOWN_CENTER: (f64, f64) = (38.96165, -77.36346);
const TYSONS_CORNER_CENTER: (f64, f64) = (38.9173, -77.22093);
const LEESBURG: (f64, f64) = (39.1153, -77.5636);
const LEESBURG_SOUTH: (f64, f64) = (39.1053, -77.5636);
const ONE_LOUDOUN: (f64, f64) = (39.0525, -77.4614);
const DUNN_LORING: (f64, f64) = (38.8836, -77.2286);
const ROSSLYN: (f64, f64) = (38.8966, -77.0707);
const POTOMAC_MILLS: (f64, f64) = (38.6418, -77.2989);
const STAFFORD: (f64, f64) = (38.4890, -77.3700);
const DULLES_AIRPORT: (f64, f64) = (38.9531, -77.4565);
const REAGAN_AIRPORT: (f64, f64) = (38.8512, -77.0402);
const NEW_YORK: (f64, f64) = (40.7128, -74.0060);

fn at((latitude, longitude): (f64, f64)) -> Value {
    json!({ "latitude": latitude, "longitude": longitude })
}

fn port(name: &str, default: u16) -> u16 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

#[derive(Clone, Default)]
struct LogBuffer(Arc<Mutex<Vec<u8>>>);

impl Write for LogBuffer {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// Everything the server would log in production (same fixed filter), captured for inspection.
fn logs() -> &'static LogBuffer {
    static LOGS: OnceLock<LogBuffer> = OnceLock::new();
    LOGS.get_or_init(|| {
        let buffer = LogBuffer::default();
        let writer = buffer.clone();
        tracing_subscriber::registry()
            .with(
                tracing_subscriber::fmt::layer()
                    .json()
                    .with_writer(move || writer.clone()),
            )
            .with(log_filter())
            .init();
        buffer
    })
}

struct Harness {
    base: String,
    http: reqwest::Client,
    _lanes: Option<RwLockReadGuard<'static, ()>>,
}

/// A tool call's outcome: structured content, the `isError` flag, and the text content.
struct Called {
    result: Value,
    is_error: bool,
    text: String,
}

async fn serve(app: Router) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{address}")
}

/// Same roles as production; only IAM/TLS is replaced for the local container.
fn database(points_role: &str) -> Database {
    let pg_port = port("MCP_E2E_PG_PORT", 55432);
    Database {
        connect: Arc::new(move |user: String| {
            Box::pin(async move {
                let (client, connection) = tokio_postgres::Config::new()
                    .host("127.0.0.1")
                    .port(pg_port)
                    .dbname(DATABASE)
                    .user(&user)
                    .connect(NoTls)
                    .await?;
                tokio::spawn(connection);
                Ok(client)
            })
        }),
        points_role: points_role.into(),
        pricing_role: "pricing_caller".into(),
    }
}

async fn connect_as(role: &str) -> tokio_postgres::Client {
    (database(role).connect)(role.into()).await.unwrap()
}

/// A server whose answers no lane change can disturb while the harness lives.
async fn start() -> Harness {
    let lanes = LANES.read().await;
    Harness {
        _lanes: Some(lanes),
        ..start_with(database("tollchat_agent")).await
    }
}

async fn start_with(database: Database) -> Harness {
    logs();
    let base = serve(router(App { database }, &["127.0.0.1"])).await;
    let http = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .unwrap();
    Harness {
        base,
        http,
        _lanes: None,
    }
}

impl Harness {
    fn post(&self, body: impl Into<reqwest::Body>) -> reqwest::RequestBuilder {
        self.http
            .post(format!("{}/mcp", self.base))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream")
            .header("MCP-Protocol-Version", "2025-11-25")
            .body(body)
    }

    async fn rpc(&self, method: &str, params: Value) -> Value {
        let body = json!({ "jsonrpc": "2.0", "id": 1, "method": method, "params": params });
        let response = self.post(body.to_string()).send().await.unwrap();
        assert_eq!(response.status(), 200);
        response.json().await.unwrap()
    }

    async fn call_with(&self, arguments: Value) -> Called {
        let response = self
            .rpc(
                "tools/call",
                json!({ "name": "find_toll_ramps", "arguments": arguments }),
            )
            .await;
        let result = &response["result"];
        Called {
            result: result["structuredContent"].clone(),
            is_error: result["isError"] == true,
            text: result["content"][0]["text"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
        }
    }

    async fn call(&self, origin: (f64, f64), destination: (f64, f64)) -> Called {
        self.call_with(json!({ "origin": at(origin), "destination": at(destination) }))
            .await
    }

    async fn find(&self, origin: (f64, f64), destination: (f64, f64)) -> Value {
        let called = self.call(origin, destination).await;
        assert!(!called.is_error, "{}", called.result);
        called.result
    }
}

async fn revalidate(origin: &str, destination: &str) -> String {
    let row = connect_as("pricing_caller")
        .await
        .query_one(
            "SELECT status FROM oracle.validate_pricing_route($1, $2)",
            &[&origin, &destination],
        )
        .await
        .unwrap();
    row.get("status")
}

fn options(result: &Value) -> &Vec<Value> {
    result["options"].as_array().expect("options")
}

fn entry_ids(result: &Value) -> Vec<&str> {
    options(result)
        .iter()
        .map(|option| option["entry"]["point_id"].as_str().unwrap())
        .collect()
}

fn close(a: &Value, b: f64) -> bool {
    (a.as_f64().unwrap() - b).abs() <= 0.11
}

/// Every option is a validated route, ranked by its stated score, with consistent parts.
async fn assert_well_formed(result: &Value) {
    let mut previous = f64::MIN;
    for option in options(result) {
        let entry = option["entry"]["point_id"].as_str().unwrap();
        let exit = option["exit"]["point_id"].as_str().unwrap();
        assert_eq!(revalidate(entry, exit).await, "valid", "{entry} -> {exit}");
        let route_id = option["route_id"].as_str().unwrap();
        assert!(
            route_id.starts_with(&format!("{entry}>")) && route_id.ends_with(&format!(">{exit}"))
        );

        let access = &option["access_miles"];
        let score = &option["score"];
        let access_total =
            access["origin"].as_f64().unwrap() + access["destination"].as_f64().unwrap();
        assert!(close(&score["access_miles"], access_total), "{option}");
        let facilities = option["facilities"].as_array().unwrap();
        assert!(close(
            &score["facility_penalty_miles"],
            2.0 * (facilities.len() as f64 - 1.0)
        ));
        let total = score["total"].as_f64().unwrap();
        assert!(total >= previous - 0.1, "ranked by score: {result}");
        previous = total;

        // Segments chain from the entry to the exit, and their facilities follow `facilities`.
        let segments = option["segments"].as_array().unwrap();
        assert!(!segments.is_empty(), "{option}");
        let mut seen: Vec<&Value> = segments.iter().map(|s| &s["facility"]).collect();
        seen.dedup();
        assert_eq!(seen, facilities.iter().collect::<Vec<_>>(), "{option}");
        let miles: f64 = segments
            .iter()
            .map(|s| s["straight_line_miles"].as_f64().unwrap())
            .sum();
        assert!(
            (option["total_straight_line_miles"].as_f64().unwrap() - miles).abs()
                <= 0.06 * segments.len() as f64
        );
        for pair in segments.windows(2) {
            let stretch = |s: &Value| {
                (
                    s["facility"].clone(),
                    s["entry_point_id"].clone(),
                    s["exit_point_id"].clone(),
                )
            };
            assert_ne!(
                stretch(&pair[0]),
                stretch(&pair[1]),
                "one segment per stretch: {option}"
            );
        }
        assert!(
            segments
                .iter()
                .all(|s| s["pricing_keys"].as_array().is_some_and(|k| !k.is_empty()))
        );
        for segment in segments {
            for end in ["entry_point_id", "exit_point_id"] {
                assert!(
                    route_id.contains(segment[end].as_str().unwrap()),
                    "{option}"
                );
            }
        }
    }
}

#[tokio::test]
async fn invalid_coordinates_get_errors_that_say_what_to_fix() {
    let harness = start().await;
    let tysons = at(TYSONS_CORNER_CENTER);
    for (arguments, message) in [
        (
            json!({ "origin": { "longitude": -77.36 }, "destination": tysons }),
            "origin.latitude is missing",
        ),
        (
            json!({ "origin": tysons, "destination": { "latitude": 38.96 } }),
            "destination.longitude is missing",
        ),
        (
            json!({ "origin": { "latitude": 91, "longitude": -77.36 }, "destination": tysons }),
            "origin.latitude 91 is outside -90 to 90",
        ),
        (
            json!({ "origin": tysons, "destination": { "latitude": 38.96, "longitude": -181 } }),
            "destination.longitude -181 is outside -180 to 180",
        ),
        (
            json!({ "origin": { "latitude": -77.36, "longitude": 38.96 }, "destination": tysons }),
            "origin.latitude -77.36 is outside the plausible range for this service; \
             did you swap latitude and longitude?",
        ),
        (
            json!({ "origin": { "latitude": "38.96", "longitude": "-77.36" }, "destination": tysons }),
            "origin.latitude must be a number, not \"38.96\"",
        ),
        (
            json!({ "origin": { "latitude": null, "longitude": -77.36 }, "destination": tysons }),
            "origin.latitude must be a number, not null",
        ),
        (
            json!({ "origin": { "latitude": 38.96, "longitude": null }, "destination": tysons }),
            "origin.longitude must be a number, not null",
        ),
        (
            json!({ "origin": null, "destination": tysons }),
            "origin must be an object with named latitude and longitude fields",
        ),
        // Never positional: either order of a bare pair would be a silent guess.
        (
            json!({ "origin": [38.96, -77.36], "destination": tysons }),
            "origin must be an object with named latitude and longitude fields",
        ),
        (
            json!({ "origin": { "latitude": 38.96, "longitude": -77.36, "altitude": 0 }, "destination": tysons }),
            "origin.altitude is not accepted",
        ),
        (
            json!({ "origin": at(RESTON_TOWN_CENTER), "destination": tysons, "extra": 1 }),
            "unknown field `extra`",
        ),
        (json!({ "origin": tysons }), "missing field `destination`"),
        // The removed v1 input fails loudly instead of being guessed at.
        (
            json!({ "origin": "Reston Town Center", "destination": "Tysons Corner Center" }),
            "origin must be an object with named latitude and longitude fields",
        ),
    ] {
        let called = harness.call_with(arguments.clone()).await;
        assert!(called.is_error, "{arguments}");
        assert!(
            called.text.contains(message),
            "{arguments}: {}",
            called.text
        );
        assert!(called.result.is_null(), "no result for bad input");
    }
}

#[tokio::test]
async fn muse_reston_to_tysons_returns_validated_ranked_options() {
    // Bound, not temporary: the harness holds the lane lock through revalidation below.
    let harness = start().await;
    let result = harness.find(RESTON_TOWN_CENTER, TYSONS_CORNER_CENTER).await;
    assert_eq!(result["status"], "resolved", "{result}");
    assert_eq!(
        result["origin"],
        json!({ "latitude": 38.96165, "longitude": -77.36346, "coverage": "covered" })
    );
    assert_eq!(
        result["destination"],
        json!({ "latitude": 38.9173, "longitude": -77.22093, "coverage": "covered" })
    );
    assert!((1..=3).contains(&options(&result).len()), "{result}");
    assert_well_formed(&result).await;
    assert!(result.get("reversible_lanes").is_none());
    let best = &options(&result)[0];
    assert_eq!(best["entry"]["role"], "entry");
    assert_eq!(best["entry"]["network"], "dtr");
    assert!(best["entry"]["direction"].is_string());
    // The Dulles Toll Road charges twice between these exits: one segment, two pricing keys.
    assert_eq!(best["segments"].as_array().map(Vec::len), Some(1), "{best}");
    assert_eq!(
        best["segments"][0]["pricing_keys"].as_array().map(Vec::len),
        Some(2)
    );
    assert_eq!(
        best["total_straight_line_miles"],
        best["segments"][0]["straight_line_miles"]
    );
    // Shown as 0.8 miles each, but Exit 12 is nearer (0.77 against Exit 11's 0.83).
    assert_eq!(best["route_id"], "dtr:12:entry:EB>dtr:1819:exit:EB");

    // For the handoff: compare with the v1 landmark baseline (DTR Exit 12 EB entry,
    // Exit 18/19 EB and Westpark Drive SB exits); differences are expected, not failures.
    for option in options(&result) {
        eprintln!(
            "reston->tysons: {} access {} score {}",
            option["route_id"], option["access_miles"], option["score"]
        );
    }
}

#[tokio::test]
async fn each_toll_road_has_a_routable_trip() {
    let harness = start().await;
    for (origin, destination, facility) in [
        (LEESBURG, ONE_LOUDOUN, "greenway"),
        (RESTON_TOWN_CENTER, TYSONS_CORNER_CENTER, "dtr"),
        (DUNN_LORING, ROSSLYN, "i66"),
        (DUNN_LORING, TYSONS_CORNER_CENTER, "i95_i495"),
    ] {
        let result = harness.find(origin, destination).await;
        assert_eq!(result["status"], "resolved", "{facility}: {result}");
        assert_well_formed(&result).await;
        let uses = options(&result).iter().any(|option| {
            option["facilities"]
                .as_array()
                .unwrap()
                .contains(&json!(facility))
        });
        assert!(uses, "{facility}: {result}");
    }
}

#[tokio::test]
async fn approach_variants_of_one_route_are_listed_once() {
    // Several I-66 catalog points share the Beltway interchange near Dunn Loring.
    let harness = start().await;
    let result = harness.find(DUNN_LORING, ROSSLYN).await;
    assert_eq!(result["status"], "resolved", "{result}");
    assert!(options(&result).len() >= 2, "{result}");
    let routes: Vec<_> = options(&result)
        .iter()
        .map(|option| (option["access_miles"].clone(), option["facilities"].clone()))
        .collect();
    for (i, route) in routes.iter().enumerate() {
        assert!(!routes[..i].contains(route), "duplicate route: {result}");
    }
}

#[tokio::test]
async fn dulles_trips_start_and_end_at_the_airport() {
    let harness = start().await;
    let from = harness.find(DULLES_AIRPORT, TYSONS_CORNER_CENTER).await;
    assert_eq!(from["status"], "resolved", "{from}");
    assert_well_formed(&from).await;
    let airport = &options(&from)[0]["entry"];
    assert_eq!(airport["point_id"], "airport_iad", "{from}");
    assert_eq!(airport["role"], "airport");
    assert!(
        airport.get("direction").is_none(),
        "airports omit direction: {airport}"
    );

    let to = harness.find(TYSONS_CORNER_CENTER, DULLES_AIRPORT).await;
    assert_eq!(to["status"], "resolved", "{to}");
    assert_well_formed(&to).await;
    assert!(
        options(&to)
            .iter()
            .any(|o| o["exit"]["point_id"] == "airport_iad"),
        "{to}"
    );
}

/// Replaces the reversible lanes' live state; `None` removes it.
async fn set_lanes(admin: &tokio_postgres::Client, statuses: Option<(&str, &str)>) {
    admin
        .execute(
            "DELETE FROM pricing.trip_pricing_i95 WHERE s3_key = 'e2e-lanes'",
            &[],
        )
        .await
        .unwrap();
    let Some((northbound, southbound)) = statuses else {
        return;
    };
    admin
        .execute(
            "INSERT INTO pricing.trip_pricing_i95 (interval_end_at, current_at, calculated_at, corridor_id,
                 corridor_name, od_pair_id, od_pair_name, start_zone_id, end_zone_id, end_zone_name,
                 zone_toll_rate_usd, link_status, s3_key)
             VALUES (date_trunc('minute', now()), now(), now(), 1, 'I-95-NB', 1132, 'e2e', 1, 2, 'e2e', 0,
                     $1, 'e2e-lanes'),
                    (date_trunc('minute', now()), now(), now(), 2, 'I-95-SB', 1151, 'e2e', 3, 4, 'e2e', 0,
                     $2, 'e2e-lanes')",
            &[&northbound, &southbound],
        )
        .await
        .unwrap();
}

#[tokio::test]
async fn reversible_lane_trips_follow_the_live_direction() {
    let _exclusive = LANES.write().await;
    let harness = start_with(database("tollchat_agent")).await;
    let admin = connect_as("postgres").await;
    let uses_dca = |result: &Value| entry_ids(result).contains(&"airport_dca");

    // The disposable database starts with no lane data.
    set_lanes(&admin, None).await;
    let unknown = harness.find(POTOMAC_MILLS, STAFFORD).await;
    assert_eq!(unknown["status"], "availability_unknown", "{unknown}");
    assert_eq!(unknown["options"], json!([]));
    assert_eq!(
        unknown["reversible_lanes"],
        json!({ "direction": "unknown" })
    );
    let dca_unknown = harness.find(REAGAN_AIRPORT, TYSONS_CORNER_CENTER).await;
    assert_eq!(dca_unknown["status"], "resolved", "{dca_unknown}");
    assert_well_formed(&dca_unknown).await;
    assert!(!uses_dca(&dca_unknown), "{dca_unknown}");

    set_lanes(&admin, Some(("NORTHBOUND_OPEN", "CLOSED"))).await;
    let southbound = harness.find(POTOMAC_MILLS, STAFFORD).await;
    assert_eq!(
        southbound["status"], "currently_unavailable",
        "{southbound}"
    );
    assert_eq!(southbound["options"], json!([]));
    assert_eq!(
        southbound["reversible_lanes"],
        json!({ "direction": "northbound" })
    );
    let northbound = harness.find(STAFFORD, POTOMAC_MILLS).await;
    assert_eq!(northbound["status"], "resolved", "{northbound}");
    assert!(northbound.get("reversible_lanes").is_none());
    assert_well_formed(&northbound).await;
    for option in options(&northbound) {
        assert_eq!(option["facilities"], json!(["i95_i495"]), "{northbound}");
        assert_eq!(
            option["reversible_lanes"],
            json!({ "direction": "northbound" })
        );
    }
    // DCA connects only through the reversible lanes: southbound departures, else a normal entry.
    let dca_northbound = harness.find(REAGAN_AIRPORT, TYSONS_CORNER_CENTER).await;
    assert_well_formed(&dca_northbound).await;
    assert!(!uses_dca(&dca_northbound), "{dca_northbound}");

    set_lanes(&admin, Some(("CLOSED", "SOUTHBOUND_OPEN"))).await;
    let dca_southbound = harness.find(REAGAN_AIRPORT, TYSONS_CORNER_CENTER).await;
    assert_well_formed(&dca_southbound).await;
    assert!(uses_dca(&dca_southbound), "{dca_southbound}");
    for option in options(&dca_southbound) {
        if option["entry"]["point_id"] == "airport_dca" {
            assert!(option["entry"].get("direction").is_none());
            assert_eq!(
                option["reversible_lanes"],
                json!({ "direction": "southbound" })
            );
        }
    }
    set_lanes(&admin, None).await;
    eprintln!(
        "dca->tysons entries: unknown {:?}, northbound {:?}, southbound {:?}",
        entry_ids(&dca_unknown),
        entry_ids(&dca_northbound),
        entry_ids(&dca_southbound)
    );
}

#[tokio::test]
async fn same_place_and_out_of_area_trips_have_their_own_statuses() {
    let harness = start().await;
    let same = harness.call(RESTON_TOWN_CENTER, RESTON_TOWN_CENTER).await;
    assert!(!same.is_error);
    assert_eq!(same.result["status"], "same_location", "{}", same.result);
    assert_eq!(same.result["options"], json!([]));

    let outside = harness.find(NEW_YORK, TYSONS_CORNER_CENTER).await;
    assert_eq!(outside["status"], "outside_coverage", "{outside}");
    assert_eq!(outside["origin"]["coverage"], "outside_coverage");
    assert_eq!(outside["destination"]["coverage"], "covered");
    assert_eq!(outside["options"], json!([]));

    // Both ends sit at the Greenway's last interchange, so no toll trip joins them.
    let none = harness.find(LEESBURG, LEESBURG_SOUTH).await;
    assert_eq!(none["status"], "no_valid_route", "{none}");
    assert_eq!(none["options"], json!([]));
}

#[tokio::test]
async fn repeated_calls_agree_and_text_is_a_short_summary() {
    let harness = start().await;
    let first = harness.call(RESTON_TOWN_CENTER, TYSONS_CORNER_CENTER).await;
    let second = harness.call(RESTON_TOWN_CENTER, TYSONS_CORNER_CENTER).await;
    let without_time = |called: &Called| {
        let mut result = called.result.clone();
        let time = result.as_object_mut().unwrap().remove("calculated_at");
        let time = time.unwrap().as_str().unwrap().to_owned();
        // RFC 3339 in UTC, for example 2026-10-26T18:17:00.123Z.
        assert!(time.len() >= 20 && time.ends_with('Z') && time.as_bytes()[10] == b'T');
        result
    };
    assert_eq!(without_time(&first), without_time(&second));

    assert!(first.text.starts_with("resolved: "), "{}", first.text);
    assert!(first.text.contains("dtr:"), "{}", first.text);
    assert!(
        serde_json::from_str::<Value>(&first.text).is_err(),
        "not a JSON copy"
    );
    assert!(first.text.len() < 400, "{}", first.text);
}

#[tokio::test]
async fn database_failure_fails_closed() {
    let harness = start_with(database("no_such_role")).await;
    let called = harness.call(RESTON_TOWN_CENTER, TYSONS_CORNER_CENTER).await;
    assert!(called.is_error, "{}", called.result);
    assert_eq!(called.result["status"], "error");
    assert!(called.result["calculated_at"].is_string());
    assert_eq!(called.result["origin"], at(RESTON_TOWN_CENTER));
    assert_eq!(
        called.text,
        "error: TollChat could not look up ramps right now. Try again later."
    );
}

#[tokio::test]
async fn http_boundary_answers_json_and_rejects_bad_requests() {
    let harness = start().await;
    let initialize = json!({ "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": { "name": "e2e", "version": "1" } } });

    let response = harness.post(initialize.to_string()).send().await.unwrap();
    assert_eq!(response.status(), 200, "no redirect");
    assert!(
        response.headers()[CONTENT_TYPE]
            .to_str()
            .unwrap()
            .starts_with("application/json")
    );
    let body: Value = response.json().await.unwrap();
    assert_eq!(body["result"]["serverInfo"]["name"], "tollchat");
    assert_eq!(body["result"]["serverInfo"]["version"], "0.2.0");
    assert!(
        body["result"]["instructions"]
            .as_str()
            .unwrap()
            .contains("latitude")
    );

    let wrong_host = harness
        .post(initialize.to_string())
        .header("Host", "evil.example")
        .send()
        .await
        .unwrap();
    assert_eq!(wrong_host.status(), 403);

    let browser = harness
        .post(initialize.to_string())
        .header("Origin", "https://evil.example")
        .send()
        .await
        .unwrap();
    assert_eq!(browser.status(), 403);

    let oversized = harness
        .post(format!("{{\"padding\":\"{}\"}}", "x".repeat(70 * 1024)))
        .send()
        .await
        .unwrap();
    assert_eq!(oversized.status(), 413);
}

#[tokio::test]
async fn connect_doc_examples_work_verbatim() {
    let harness = start().await;
    let doc = harness
        .http
        .get(&harness.base)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    let examples: Vec<&str> = doc
        .split("```http\n")
        .skip(1)
        .map(|block| block.split("\n```").next().unwrap())
        .collect();
    assert_eq!(
        examples.len(),
        5,
        "2025 handshake (4 requests) and one 2026-07-28 call"
    );

    for example in examples {
        let (head, body) = example.split_once("\n\n").unwrap();
        let mut lines = head.lines();
        assert_eq!(lines.next(), Some("POST /mcp HTTP/1.1"));
        let mut request = harness
            .http
            .post(format!("{}/mcp", harness.base))
            .body(body.to_owned());
        for line in lines {
            let (name, value) = line.split_once(": ").unwrap();
            // The local server answers for 127.0.0.1 instead of mcp.tollchat.ai.
            if name != "Host" {
                request = request.header(name, value);
            }
        }
        let response = request.send().await.unwrap();
        let status = response.status().as_u16();
        let text = response.text().await.unwrap();
        if body.contains("\"notifications/initialized\"") {
            assert_eq!(status, 202, "{text}");
            continue;
        }
        assert_eq!(status, 200, "{example}\n{text}");
        let reply: Value = serde_json::from_str(&text).unwrap();
        assert!(reply.get("error").is_none(), "{reply}");
        if body.contains("\"tools/call\"") {
            assert_eq!(
                reply["result"]["structuredContent"]["status"], "resolved",
                "{reply}"
            );
        }
    }
}

#[tokio::test]
async fn docs_cover_every_tool_status_and_privacy() {
    let harness = start().await;
    let doc = harness
        .http
        .get(&harness.base)
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    let tools = harness.rpc("tools/list", json!({})).await;
    let tools = tools["result"]["tools"].as_array().unwrap();
    assert!(!tools.is_empty());
    for tool in tools {
        let name = tool["name"].as_str().unwrap();
        assert!(
            doc.contains(&format!("## Tool: `{name}`")),
            "connect doc misses {name}"
        );
        assert_eq!(tool["annotations"]["readOnlyHint"], true);
        assert_eq!(tool["annotations"]["idempotentHint"], true);
    }
    // Both ends are documented as named latitude/longitude fields, never an array.
    let schema = tools[0]["inputSchema"].to_string();
    assert!(
        schema.contains("latitude") && schema.contains("longitude"),
        "{schema}"
    );
    for status in [
        "resolved",
        "same_location",
        "outside_coverage",
        "no_valid_route",
        "currently_unavailable",
        "availability_unknown",
        "error",
    ] {
        assert!(
            doc.contains(&format!("| `{status}`")),
            "connect doc misses {status}"
        );
    }
    let privacy = harness
        .http
        .get(format!("{}/privacy", harness.base))
        .send()
        .await
        .unwrap();
    assert_eq!(privacy.status(), 200);
    assert!(privacy.text().await.unwrap().contains("privacy notice"));
}

#[tokio::test]
async fn logs_never_contain_coordinates() {
    let harness = start().await;
    harness.find(RESTON_TOWN_CENTER, TYSONS_CORNER_CENTER).await;
    harness.find(NEW_YORK, TYSONS_CORNER_CENTER).await;
    let failed = start_with(database("no_such_role"))
        .await
        .call(RESTON_TOWN_CENTER, ROSSLYN)
        .await;
    assert!(failed.is_error, "{}", failed.result);

    let logged = String::from_utf8(logs().0.lock().unwrap().clone()).unwrap();
    assert!(
        logged.contains("\"tool\":\"find_toll_ramps\""),
        "capture works: {logged}"
    );
    assert!(logged.contains("\"stage\":\"load_points\""), "{logged}");
    for text in [
        "38.96165",
        "-77.36346",
        "38.9173",
        "-77.22093",
        "40.7128",
        "-74.006",
        "-77.0707",
    ] {
        assert!(!logged.contains(text), "log contains {text:?}: {logged}");
    }
}
