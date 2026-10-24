//! End to end: the real router over HTTP and real MCP JSON-RPC, against the disposable oracle
//! database with its real least-privilege roles, DynamoDB Local, and a canned Amazon Location
//! SearchText stub (the only fake: the real service needs credentials and costs money).
//! Run through `e2e.sh`, which starts the containers.

use std::io::Write;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use aws_config::{BehaviorVersion, Region};
use aws_sdk_dynamodb::types::{
    AttributeDefinition, AttributeValue, BillingMode, KeySchemaElement, KeyType,
    ScalarAttributeType,
};
use axum::extract::State;
use axum::http::StatusCode;
use axum::http::header::CONTENT_TYPE;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use mcp_server::{App, Database, log_filter, router};
use serde_json::{Value, json};
use tokio_postgres::NoTls;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

const DATABASE: &str = "nova_toll_mcp_e2e";
/// SearchText answers this query with an error whose message repeats the query.
const FAILING_PLACE: &str = "Error Place 4417";

/// Canned SearchText answers: (title, address, [lon, lat]).
fn canned(query: &str) -> Vec<(&'static str, &'static str, [f64; 2])> {
    match query {
        "Reston Town Center" => vec![(
            "Reston Town Center",
            "11900 Market St, Reston, VA 20190, United States",
            [-77.3570, 38.9586],
        )],
        "Tysons Corner Center" => vec![(
            "Tysons Corner Center",
            "1961 Chain Bridge Rd, Tysons, VA 22102, United States",
            [-77.2210, 38.9180],
        )],
        "Potomac Mills" => vec![(
            "Potomac Mills",
            "Woodbridge, VA 22192, United States",
            [-77.2989, 38.6418],
        )],
        "Stafford" => vec![(
            "Stafford",
            "Stafford, VA 22554, United States",
            [-77.3700, 38.4890],
        )],
        "Leesburg" => vec![(
            "Leesburg",
            "Leesburg, VA 20175, United States",
            [-77.5636, 39.1153],
        )],
        "Dunn Loring" => vec![(
            "Dunn Loring",
            "Dunn Loring, VA, United States",
            [-77.2286, 38.8836],
        )],
        "Rosslyn" => vec![(
            "Rosslyn",
            "Rosslyn, Arlington, VA, United States",
            [-77.0707, 38.8966],
        )],
        "Dulles Airport" => vec![(
            "Washington Dulles International Airport",
            "1 Saarinen Cir, Dulles, VA 20166, United States",
            [-77.4565, 38.9531],
        )],
        "Richmond" => vec![(
            "Richmond",
            "Richmond, VA, United States",
            [-77.4360, 37.5407],
        )],
        // Two covered places far apart: genuinely ambiguous.
        "Washington" => vec![
            (
                "Washington",
                "Washington, DC, United States",
                [-77.0369, 38.9072],
            ),
            (
                "Washington Dulles International Airport",
                "Dulles, VA 20166, United States",
                [-77.4565, 38.9531],
            ),
        ],
        // The Massachusetts match is far from any toll road, so it must not make this ambiguous.
        "Springfield" => vec![
            (
                "Springfield",
                "Springfield, VA, United States",
                [-77.1873, 38.7849],
            ),
            (
                "Springfield",
                "Springfield, MA, United States",
                [-72.5898, 42.1015],
            ),
        ],
        _ => vec![],
    }
}

const PLACE_TEXTS: [&str; 13] = [
    "Reston",
    "Tysons",
    "Potomac Mills",
    "Stafford",
    "Leesburg",
    "Dunn Loring",
    "Rosslyn",
    "Dulles",
    "Saarinen",
    "Richmond",
    "Springfield",
    "Nowhere Junction",
    FAILING_PLACE,
];

fn port(name: &str, default: u16) -> u16 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

fn today() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        / 86_400
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
    dynamodb: aws_sdk_dynamodb::Client,
    table: String,
    searches: Arc<Mutex<Vec<Value>>>,
}

async fn search_text(
    State(searches): State<Arc<Mutex<Vec<Value>>>>,
    Json(body): Json<Value>,
) -> Response {
    let query = body["QueryText"].as_str().unwrap_or_default().to_owned();
    searches.lock().unwrap().push(body);
    if query == FAILING_PLACE {
        let error = json!({ "message": format!("Invalid query: {query}") });
        return (
            StatusCode::BAD_REQUEST,
            [("x-amzn-errortype", "ValidationException")],
            Json(error),
        )
            .into_response();
    }
    let items: Vec<Value> = canned(&query)
        .into_iter()
        .enumerate()
        .map(|(i, (title, label, position))| {
            json!({ "PlaceId": format!("stub-{i}"), "PlaceType": "PointOfInterest", "Title": title,
                    "Address": { "Label": label }, "Position": position })
        })
        .collect();
    (
        [
            ("x-amz-geo-pricing-bucket", "Core"),
            (CONTENT_TYPE.as_str(), "application/json"),
        ],
        Json(json!({ "ResultItems": items })),
    )
        .into_response()
}

async fn serve(app: Router) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{address}")
}

fn database() -> Database {
    let pg_port = port("MCP_E2E_PG_PORT", 55432);
    Database {
        // Same roles as production; only IAM/TLS is replaced for the local container.
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
        points_role: "tollchat_agent".into(),
        pricing_role: "pricing_caller".into(),
    }
}

async fn connect_as(role: &str) -> tokio_postgres::Client {
    (database().connect)(role.into()).await.unwrap()
}

async fn start() -> Harness {
    start_with(true).await
}

/// `create_table: false` points the server at a lookup table that does not exist.
async fn start_with(create_table: bool) -> Harness {
    logs();
    let searches = Arc::new(Mutex::new(Vec::new()));
    let stub = serve(
        Router::new()
            .route("/v2/search-text", post(search_text))
            .with_state(searches.clone()),
    )
    .await;

    let credentials = aws_sdk_dynamodb::config::Credentials::new("e2e", "e2e", None, None, "e2e");
    let places = aws_sdk_geoplaces::Client::from_conf(
        aws_sdk_geoplaces::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new("us-east-1"))
            .credentials_provider(credentials.clone())
            .endpoint_url(stub)
            .build(),
    );
    let dynamodb = aws_sdk_dynamodb::Client::from_conf(
        aws_sdk_dynamodb::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new("us-east-1"))
            .credentials_provider(credentials)
            .endpoint_url(format!(
                "http://127.0.0.1:{}",
                port("MCP_E2E_DDB_PORT", 58000)
            ))
            .build(),
    );
    static TABLES: AtomicUsize = AtomicUsize::new(0);
    let table = format!(
        "lookups-{}-{}",
        std::process::id(),
        TABLES.fetch_add(1, Ordering::Relaxed)
    );
    if create_table {
        dynamodb
            .create_table()
            .table_name(&table)
            .billing_mode(BillingMode::PayPerRequest)
            .attribute_definitions(
                AttributeDefinition::builder()
                    .attribute_name("day")
                    .attribute_type(ScalarAttributeType::N)
                    .build()
                    .unwrap(),
            )
            .key_schema(
                KeySchemaElement::builder()
                    .attribute_name("day")
                    .key_type(KeyType::Hash)
                    .build()
                    .unwrap(),
            )
            .send()
            .await
            .unwrap();
    }

    let app = App {
        places,
        dynamodb: dynamodb.clone(),
        lookup_table: table.clone(),
        database: database(),
    };
    let base = serve(router(app, &["127.0.0.1"])).await;
    let http = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .unwrap();
    Harness {
        base,
        http,
        dynamodb,
        table,
        searches,
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

    /// The tool result: its structured content, and whether it is a tool error.
    async fn call(&self, origin: &str, destination: &str) -> (Value, bool) {
        let arguments = json!({ "origin": origin, "destination": destination });
        let response = self
            .rpc(
                "tools/call",
                json!({ "name": "find_toll_ramps", "arguments": arguments }),
            )
            .await;
        let result = &response["result"];
        (
            result["structuredContent"].clone(),
            result["isError"] == true,
        )
    }

    async fn find(&self, origin: &str, destination: &str) -> Value {
        let (result, is_error) = self.call(origin, destination).await;
        assert!(!is_error, "{result}");
        result
    }

    fn searches(&self) -> usize {
        self.searches.lock().unwrap().len()
    }

    async fn lookups_today(&self) -> Option<u64> {
        let item = self
            .dynamodb
            .get_item()
            .table_name(&self.table)
            .key("day", AttributeValue::N(today().to_string()))
            .send()
            .await
            .unwrap();
        Some(item.item()?.get("lookups")?.as_n().ok()?.parse().unwrap())
    }

    async fn set_lookups_today(&self, lookups: u64) {
        self.dynamodb
            .put_item()
            .table_name(&self.table)
            .item("day", AttributeValue::N(today().to_string()))
            .item("lookups", AttributeValue::N(lookups.to_string()))
            .send()
            .await
            .unwrap();
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

#[tokio::test]
async fn resolved_trip_returns_only_validated_ranked_options() {
    let harness = start().await;
    let result = harness
        .find("Reston Town Center", "Tysons Corner Center")
        .await;

    assert_eq!(result["status"], "resolved", "{result}");
    assert_eq!(result["origin"]["match"], "resolved");
    assert_eq!(result["origin"]["name"], "Reston Town Center");
    assert!((1..=3).contains(&options(&result).len()), "{result}");
    let mut previous = f64::MIN;
    for option in options(&result) {
        let entry = option["entry"]["point_id"].as_str().unwrap();
        let exit = option["exit"]["point_id"].as_str().unwrap();
        assert_eq!(revalidate(entry, exit).await, "valid", "{entry} -> {exit}");
        // Total access miles, with each extra toll road counted as 2 miles (rounding allowed).
        let access = &option["access_miles"];
        let facilities = option["facilities"].as_array().unwrap().len() as f64;
        let score = access["origin"].as_f64().unwrap()
            + access["destination"].as_f64().unwrap()
            + 2.0 * (facilities - 1.0);
        assert!(score >= previous - 0.1, "{result}");
        previous = score;
    }

    // Two lookups per call, biased (not boxed) to the service area, Core bucket, never stored.
    assert_eq!(harness.lookups_today().await, Some(2));
    for search in harness.searches.lock().unwrap().iter() {
        assert_eq!(search["IntendedUse"], "SingleUse");
        assert_eq!(search["MaxResults"], 3);
        assert_eq!(search["Filter"], json!({ "IncludeCountries": ["USA"] }));
        assert_eq!(search["BiasPosition"].as_array().map(Vec::len), Some(2));
        assert!(search.get("AdditionalFeatures").is_none());
    }
}

#[tokio::test]
async fn approach_variants_of_one_route_are_listed_once() {
    // Several I-66 catalog points share the Beltway interchange near Dunn Loring.
    let result = start().await.find("Dunn Loring", "Rosslyn").await;
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
async fn airport_trip_starts_at_the_airport() {
    let result = start()
        .await
        .find("Dulles Airport", "Tysons Corner Center")
        .await;
    assert_eq!(result["status"], "resolved", "{result}");
    assert_eq!(
        options(&result)[0]["entry"]["point_id"],
        "airport_iad",
        "{result}"
    );
    for option in options(&result) {
        let entry = option["entry"]["point_id"].as_str().unwrap();
        let exit = option["exit"]["point_id"].as_str().unwrap();
        assert_eq!(revalidate(entry, exit).await, "valid", "{entry} -> {exit}");
    }
}

#[tokio::test]
async fn i95_trips_follow_the_live_lane_direction() {
    let harness = start().await;
    // The disposable database has no I-95 lane-direction data yet.
    let unknown = harness.find("Potomac Mills", "Stafford").await;
    assert_eq!(unknown["status"], "availability_unknown", "{unknown}");
    assert_eq!(unknown["options"], json!([]));

    // Fresh feed data: the reversible lanes run northbound.
    let admin = connect_as("postgres").await;
    admin
        .batch_execute(
            "INSERT INTO pricing.trip_pricing_i95 (interval_end_at, current_at, calculated_at, corridor_id,
                 corridor_name, od_pair_id, od_pair_name, start_zone_id, end_zone_id, end_zone_name,
                 zone_toll_rate_usd, link_status, s3_key)
             VALUES (date_trunc('minute', now()), now(), now(), 1, 'I-95-NB', 1132, 'e2e', 1, 2, 'e2e', 0,
                     'NORTHBOUND_OPEN', 'e2e-lanes'),
                    (date_trunc('minute', now()), now(), now(), 2, 'I-95-SB', 1151, 'e2e', 3, 4, 'e2e', 0,
                     'CLOSED', 'e2e-lanes')",
        )
        .await
        .unwrap();

    let southbound = harness.find("Potomac Mills", "Stafford").await;
    let northbound = harness.find("Stafford", "Potomac Mills").await;
    admin
        .batch_execute("DELETE FROM pricing.trip_pricing_i95 WHERE s3_key = 'e2e-lanes'")
        .await
        .unwrap();

    assert_eq!(
        southbound["status"], "currently_unavailable",
        "{southbound}"
    );
    assert_eq!(southbound["options"], json!([]));
    assert_eq!(northbound["status"], "resolved", "{northbound}");
    for option in options(&northbound) {
        assert_eq!(option["facilities"], json!(["i95_i495"]), "{northbound}");
    }
}

#[tokio::test]
async fn unresolvable_trips_explain_which_side_needs_attention() {
    let harness = start().await;
    for (origin, destination, status) in [
        ("Washington", "Tysons Corner Center", "ambiguous"),
        (
            "Nowhere Junction",
            "Tysons Corner Center",
            "place_not_found",
        ),
        ("Reston Town Center", "Richmond", "outside_coverage"),
        ("Leesburg", "Leesburg", "no_valid_route"),
    ] {
        let result = harness.find(origin, destination).await;
        assert_eq!(
            result["status"], status,
            "{origin} -> {destination}: {result}"
        );
        assert!(
            result
                .get("options")
                .is_none_or(|options| options == &json!([])),
            "{result}"
        );
    }
    let ambiguous = harness.find("Washington", "Tysons Corner Center").await;
    assert_eq!(
        ambiguous["origin"]["candidates"].as_array().map(Vec::len),
        Some(2)
    );
    assert_eq!(ambiguous["destination"]["match"], "resolved");

    let springfield = harness.find("Springfield", "Tysons Corner Center").await;
    assert_eq!(springfield["origin"]["match"], "resolved", "{springfield}");
    assert_eq!(
        springfield["origin"]["address"],
        "Springfield, VA, United States"
    );
}

#[tokio::test]
async fn daily_lookup_limit_stops_exactly_at_the_cap() {
    let harness = start().await;
    harness.set_lookups_today(998).await;
    let last = harness
        .find("Reston Town Center", "Tysons Corner Center")
        .await;
    assert_eq!(last["status"], "resolved");
    assert_eq!(harness.lookups_today().await, Some(1_000));

    let limited = harness
        .find("Reston Town Center", "Tysons Corner Center")
        .await;
    assert_eq!(limited["status"], "daily_lookup_limit", "{limited}");
    assert_eq!(harness.lookups_today().await, Some(1_000));
    assert_eq!(harness.searches(), 2, "no lookups after the cap");
}

#[tokio::test(flavor = "multi_thread")]
async fn concurrent_calls_cannot_overspend_the_cap() {
    let harness = Arc::new(start().await);
    harness.set_lookups_today(990).await;
    let mut calls = tokio::task::JoinSet::new();
    for _ in 0..12 {
        let harness = harness.clone();
        calls.spawn(async move {
            harness
                .find("Reston Town Center", "Tysons Corner Center")
                .await
        });
    }
    let results = calls.join_all().await;
    let count = |status: &str| results.iter().filter(|r| r["status"] == status).count();
    assert_eq!((count("resolved"), count("daily_lookup_limit")), (5, 7));
    assert_eq!(harness.lookups_today().await, Some(1_000));
    assert_eq!(harness.searches(), 10);
}

#[tokio::test]
async fn lookup_budget_failure_fails_closed() {
    let harness = start_with(false).await;
    let (result, is_error) = harness
        .call("Reston Town Center", "Tysons Corner Center")
        .await;
    assert!(is_error, "{result}");
    assert_eq!(result["status"], "error");
    assert_eq!(harness.searches(), 0, "no lookups without a budget");
}

#[tokio::test]
async fn invalid_arguments_are_rejected_without_spending_lookups() {
    let harness = start().await;
    for arguments in [
        json!({ "origin": "Reston Town Center", "destination": "Tysons Corner Center", "extra": 1 }),
        json!({ "origin": "   ", "destination": "Tysons Corner Center" }),
        json!({ "origin": "x".repeat(201), "destination": "Tysons Corner Center" }),
        json!({ "origin": "Reston Town Center" }),
    ] {
        let response = harness
            .rpc(
                "tools/call",
                json!({ "name": "find_toll_ramps", "arguments": arguments }),
            )
            .await;
        assert_eq!(response["result"]["isError"], true, "{response}");
    }
    assert_eq!(harness.lookups_today().await, None);
    assert_eq!(harness.searches(), 0);
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
    assert!(
        body["result"]["instructions"]
            .as_str()
            .unwrap()
            .contains("ambiguous")
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
    }
    for status in [
        "resolved",
        "ambiguous",
        "place_not_found",
        "outside_coverage",
        "no_valid_route",
        "currently_unavailable",
        "availability_unknown",
        "daily_lookup_limit",
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
async fn logs_never_contain_places_or_coordinates() {
    let harness = start().await;
    harness
        .find("Reston Town Center", "Tysons Corner Center")
        .await;
    harness.find("Springfield", "Richmond").await;
    let (failed, is_error) = harness.call(FAILING_PLACE, "Rosslyn").await;
    assert!(is_error, "{failed}");
    assert_eq!(failed["status"], "error");

    let logged = String::from_utf8(logs().0.lock().unwrap().clone()).unwrap();
    assert!(
        logged.contains("\"tool\":\"find_toll_ramps\""),
        "capture works: {logged}"
    );
    assert!(logged.contains("\"stage\":\"search_text\""), "{logged}");
    // Longitudes (negative here) cannot collide with timestamps the way latitudes can.
    for text in PLACE_TEXTS.iter().chain(&["-77.", "-72.", "Market St"]) {
        assert!(!logged.contains(text), "log contains {text:?}: {logged}");
    }
}
