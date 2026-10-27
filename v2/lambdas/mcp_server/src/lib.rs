//! TollChat MCP server: Muse-facing toll tools over the TollChat routing oracle.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

use aws_credential_types::provider::{ProvideCredentials, SharedCredentialsProvider};
use aws_sigv4::http_request::{
    SignableBody, SignableRequest, SignatureLocation, SigningSettings, sign,
};
use aws_sigv4::sign::v4;
use aws_smithy_types::date_time::{DateTime, Format};
use axum::Router;
use axum::http::header::CONTENT_TYPE;
use axum::routing::get;
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, ContentBlock, Implementation, ServerCapabilities, ServerConfig};
use rmcp::transport::streamable_http_server::session::local::LocalSessionManager;
use rmcp::transport::streamable_http_server::{StreamableHttpServerConfig, StreamableHttpService};
use rmcp::{ErrorData, ServerHandler, schemars, tool, tool_handler, tool_router};
use rustls_pki_types::CertificateDer;
use rustls_pki_types::pem::PemObject;
use serde::Deserialize;
use serde_json::{Value, json};
use tokio_postgres::config::SslMode;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::filter::Targets;

const INSTRUCTIONS: &str = include_str!("instructions.md");
const CONNECT_DOC: &str = include_str!("connect.md");
const PRIVACY_DOC: &str = include_str!("privacy.md");

const MAX_ACCESS_MILES: f64 = 8.0;
/// An airport point is a candidate only for a trip that starts or ends at that airport.
const AIRPORT_MATCH_MILES: f64 = 1.5;
/// Approach variants of one interchange share a spot; keep them together.
const SAME_INTERCHANGE_MILES: f64 = 0.1;
/// Closer than this, the two ends are one place and there is no trip to route.
const SAME_LOCATION_MILES: f64 = 0.1;
const MAX_GROUPS_PER_SIDE: usize = 4;
/// Each toll road after the first adds this many miles to a route's score.
const FACILITY_PENALTY_MILES: f64 = 2.0;
/// A straight-line mile in the express lanes against one on the local roads to the ramps.
const TOLL_MILE_WEIGHT: f64 = 0.5;
const MAX_OPTIONS: usize = 3;
/// The way back may need a farther ramp than the nearest one per road (the nearest can be one the
/// return cannot reach); every extra mile adds ramp pairs to validate.
const RETURN_SEARCH_MILES: f64 = 3.0;
/// Fewest priced days of each commute weekday an estimate with an I-95/I-495 leg needs.
const MIN_PRICED_PER_WEEKDAY: i64 = 2;
/// Leaves Lambda's 25 s for the reply; a timeout then answers as a tool error, not a gateway 5xx.
const ESTIMATE_BUDGET: Duration = Duration::from_secs(20);

const POINTS_SQL: &str = "SELECT oracle.get_toll_route_prompt_points() AS points";
/// Each pair's route without today's reversible-lane state, as an estimate prices it, and for a
/// valid one, the live check of the same pair, which says whether that route is usable right now.
const ROUTES_SQL: &str = "SELECT o.id AS origin, d.id AS destination, route.status, \
     route.facility_legs, route.point_ids, live.status AS live_status, \
     live.point_ids AS live_point_ids, live.i95_evidence \
     FROM unnest($1::text[]) AS o(id) CROSS JOIN unnest($2::text[]) AS d(id) \
     CROSS JOIN LATERAL oracle.validate_ballpark_route(o.id, d.id) AS route \
     LEFT JOIN LATERAL (SELECT * FROM oracle.validate_pricing_route(o.id, d.id) \
         WHERE route.status = 'valid') AS live ON true";
/// Routes without today's reversible-lane state: an estimate prices past days.
const BALLPARK_ROUTES_SQL: &str = "SELECT o.id AS origin, d.id AS destination, route.status, \
     route.facility_legs, route.point_ids \
     FROM unnest($1::text[]) AS o(id) CROSS JOIN unnest($2::text[]) AS d(id) \
     CROSS JOIN LATERAL oracle.validate_ballpark_route(o.id, d.id) AS route";
/// The 84 completed local days the oracle samples, on the commute's weekdays.
const SAMPLE_DAYS_SQL: &str = "WITH today AS ( \
         SELECT (transaction_timestamp() AT TIME ZONE 'America/New_York')::date AS day) \
     SELECT sample.day::date::text AS day, extract(isodow FROM sample.day)::int AS isodow, \
         (today.day - 84)::text AS window_start, (today.day - 1)::text AS window_end \
     FROM today, generate_series(today.day - 84, today.day - 1, interval '1 day') AS sample(day) \
     WHERE extract(isodow FROM sample.day)::int = ANY($1::int[]) \
     ORDER BY sample.day";
/// Numbers come back as text, so no decimal or date types are needed.
const BALLPARK_SQL: &str = "SELECT complete_pair_count, eligible_date_count, coverage_percent, \
     sample_status, uses_modeled, uses_current_fixed_rates, facility_scenarios, coverage_by_weekday, \
     p25_daily_usd::text AS daily_low, p50_daily_usd::text AS daily_typical, \
     p90_daily_usd::text AS daily_high, p25_annualized_usd::text AS annual_low, \
     p50_annualized_usd::text AS annual_typical, p90_annualized_usd::text AS annual_high \
     FROM oracle.get_annual_ballpark_summary($1::jsonb, $2::text::time, $3::text::time, \
         $4::text[]::date[], $5::jsonb, $6::int, transaction_timestamp())";
/// Sampling 84 days of history (and validating many return pairs) can outlast the connection's 5 s
/// default; `ESTIMATE_BUDGET` still bounds the whole estimate.
const BALLPARK_TIMEOUT_SQL: &str = "SET LOCAL statement_timeout = '15s'";

pub type BoxError = Box<dyn std::error::Error + Send + Sync>;
pub type Connect = Arc<
    dyn Fn(String) -> Pin<Box<dyn Future<Output = Result<tokio_postgres::Client, BoxError>> + Send>>
        + Send
        + Sync,
>;

/// The oracle database, reached as one of two least-privilege roles.
pub struct Database {
    pub connect: Connect,
    /// Reads the point catalog (`tollchat_agent`).
    pub points_role: String,
    /// Validates routes the way the pricing tools do (`pricing_caller`).
    pub pricing_role: String,
}

pub struct App {
    pub database: Database,
}

/// Fixed so `RUST_LOG` can never turn on request-body logging.
pub fn log_filter() -> Targets {
    Targets::new()
        .with_default(LevelFilter::WARN)
        .with_target("mcp_server", LevelFilter::INFO)
}

pub fn router(app: App, allowed_hosts: &[&str]) -> Router {
    let app = Arc::new(app);
    let mcp = StreamableHttpService::new(
        move || Ok(TollServer::new(app.clone())),
        Arc::new(LocalSessionManager::default()),
        StreamableHttpServerConfig::default()
            .with_legacy_session_mode(false)
            .with_json_response(true)
            .with_sse_keep_alive(None)
            .with_allowed_hosts(allowed_hosts.iter().copied())
            // No browser clients: any request carrying an Origin header is rejected.
            .enforce_origin_validation()
            .with_max_request_body_bytes(64 * 1024),
    );
    Router::new()
        .route(
            "/",
            get(|| async {
                (
                    [(CONTENT_TYPE, "text/markdown; charset=utf-8")],
                    CONNECT_DOC,
                )
            }),
        )
        .route(
            "/privacy",
            get(|| async {
                (
                    [(CONTENT_TYPE, "text/markdown; charset=utf-8")],
                    PRIVACY_DOC,
                )
            }),
        )
        .route_service("/mcp", mcp)
}

/// Production database access: IAM auth tokens over TLS that trusts only the RDS CA bundle.
pub fn iam_database(
    sdk: &aws_config::SdkConfig,
    host: String,
    port: u16,
    dbname: String,
    ca_bundle_path: &str,
    points_role: String,
    pricing_role: String,
) -> Result<Database, BoxError> {
    let mut roots = rustls::RootCertStore::empty();
    for cert in CertificateDer::pem_file_iter(ca_bundle_path)? {
        roots.add(cert?)?;
    }
    let tls = tokio_postgres_rustls::MakeRustlsConnect::new(
        rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::aws_lc_rs::default_provider(),
        ))
        .with_safe_default_protocol_versions()?
        .with_root_certificates(roots)
        .with_no_client_auth(),
    );
    let credentials = sdk
        .credentials_provider()
        .ok_or("no AWS credentials provider")?;
    let region = sdk.region().ok_or("no AWS region")?.to_string();
    let connect: Connect = Arc::new(move |user: String| {
        let (tls, credentials, region, host, dbname) = (
            tls.clone(),
            credentials.clone(),
            region.clone(),
            host.clone(),
            dbname.clone(),
        );
        Box::pin(async move {
            let token = rds_auth_token(&credentials, &region, &host, port, &user).await?;
            let (client, connection) = tokio_postgres::Config::new()
                .host(&host)
                .port(port)
                .dbname(&dbname)
                .user(&user)
                .password(token)
                // Require + rustls verifies chain and hostname: libpq's verify-full.
                .ssl_mode(SslMode::Require)
                .connect_timeout(Duration::from_secs(3))
                .options("-c statement_timeout=5000")
                .connect(tls)
                .await?;
            tokio::spawn(connection);
            Ok(client)
        })
    });
    Ok(Database {
        connect,
        points_role,
        pricing_role,
    })
}

async fn rds_auth_token(
    credentials: &SharedCredentialsProvider,
    region: &str,
    host: &str,
    port: u16,
    user: &str,
) -> Result<String, BoxError> {
    let identity = credentials.provide_credentials().await?.into();
    let mut settings = SigningSettings::default();
    settings.expires_in = Some(Duration::from_secs(900));
    settings.signature_location = SignatureLocation::QueryParams;
    let params = v4::SigningParams::builder()
        .identity(&identity)
        .region(region)
        .name("rds-db")
        .time(SystemTime::now())
        .settings(settings)
        .build()?
        .into();
    let base = format!("https://{host}:{port}/?Action=connect&DBUser={user}");
    let request = SignableRequest::new("GET", &base, std::iter::empty(), SignableBody::Bytes(&[]))?;
    let (instructions, _signature) = sign(request, &params)?.into_parts();
    let mut url = url::Url::parse(&base)?;
    for (name, value) in instructions.params() {
        url.query_pairs_mut().append_pair(name, value);
    }
    Ok(url.as_str()["https://".len()..].to_owned())
}

/// A WGS-84 position in decimal degrees.
// Describes the input schema only; `position` reads the fields so its errors can name each one.
#[derive(schemars::JsonSchema)]
#[schemars(deny_unknown_fields)]
#[expect(dead_code, reason = "schema only")]
struct Coordinate {
    /// Degrees north, -90 to 90. Covered trips are near 38.9.
    #[schemars(range(min = -90.0, max = 90.0))]
    latitude: f64,
    /// Degrees east, -180 to 180. Covered trips are near -77.3.
    #[schemars(range(min = -180.0, max = 180.0))]
    longitude: f64,
}

#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct FindTollRamps {
    /// Where the trip starts. A landmark or nearby intersection is precise enough; an exact
    /// home location is not needed.
    // Parsed per side by `position`, so an error can say which end to fix.
    #[schemars(with = "Coordinate")]
    origin: Value,
    /// Where the trip ends, given the same way.
    #[schemars(with = "Coordinate")]
    destination: Value,
}

// Fields are read one by one in `commute`, so each error names the field to fix.
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct EstimateAnnualTolls {
    /// The chosen find_toll_ramps option's `entry.point_id`, exactly as returned.
    #[schemars(with = "String")]
    entry_point_id: Value,
    /// The same option's `exit.point_id`, exactly as returned.
    #[schemars(with = "String")]
    exit_point_id: Value,
    /// When the trip from the origin starts, as HH:MM 24-hour America/New_York time. Default 08:30.
    #[serde(default)]
    #[schemars(with = "Option<String>")]
    depart_at: Value,
    /// When the return trip starts, the same day, as HH:MM. Default 17:30.
    #[serde(default)]
    #[schemars(with = "Option<String>")]
    return_at: Value,
    /// Commute days of the week as lowercase English names, such as ["tuesday", "thursday"].
    /// Default monday through friday.
    #[serde(default)]
    #[schemars(with = "Option<Vec<String>>")]
    weekdays: Value,
    /// Commute days per year. Default 50 weeks: 50 times the number of weekdays.
    #[serde(default)]
    #[schemars(with = "Option<u32>", range(min = 1, max = 366))]
    annual_commute_days: Value,
}

const WEEKDAYS: [&str; 7] = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
];

/// A validated commute schedule; America/New_York wall times.
struct Commute {
    entry: String,
    exit: String,
    depart_at: String,
    return_at: String,
    /// ISO weekday numbers, Monday = 1, in calendar order.
    isodows: Vec<i32>,
    annual_days: i32,
}

impl EstimateAnnualTolls {
    fn commute(self) -> Result<Commute, String> {
        let point_id = |field: &str, value: &Value| match value.as_str() {
            Some(id) if !id.is_empty() && id.len() <= 64 => Ok(id.to_owned()),
            _ => Err(format!(
                "{field} must be a point ID string from find_toll_ramps, not {value}"
            )),
        };
        let clock = |field: &str, value: &Value, default: &str| {
            let text = match value {
                Value::Null => return Ok(default.to_owned()),
                value => value.as_str().unwrap_or_default(),
            };
            let two_digits_below = |part: &str, limit: u8| {
                part.len() == 2
                    && part.bytes().all(|b| b.is_ascii_digit())
                    && part.parse::<u8>().is_ok_and(|n| n < limit)
            };
            let valid = text
                .split_once(':')
                .is_some_and(|(h, m)| two_digits_below(h, 24) && two_digits_below(m, 60));
            if valid {
                Ok(text.to_owned())
            } else {
                Err(format!(
                    "{field} must be HH:MM in 24-hour time, such as \"08:30\", not {value}"
                ))
            }
        };
        let isodows = match &self.weekdays {
            Value::Null => vec![1, 2, 3, 4, 5],
            Value::Array(days) if (1..=7).contains(&days.len()) => {
                let mut isodows = Vec::new();
                for day in days {
                    let Some(index) = WEEKDAYS.iter().position(|name| day.as_str() == Some(*name))
                    else {
                        return Err(format!(
                            "weekdays has {day}; use lowercase English day names such as \"monday\""
                        ));
                    };
                    let isodow = i32::try_from(index).unwrap_or_default() + 1;
                    if isodows.contains(&isodow) {
                        return Err(format!("weekdays lists {day} twice"));
                    }
                    isodows.push(isodow);
                }
                isodows.sort_unstable();
                isodows
            }
            other => {
                return Err(format!(
                    "weekdays must be a list of 1 to 7 day names, not {other}"
                ));
            }
        };
        // 53 weeks of the chosen weekdays is the most a year can hold (the oracle's own limit).
        let most = 53 * isodows.len() as i32;
        let annual_days = match &self.annual_commute_days {
            Value::Null => 50 * isodows.len() as i32,
            value => match value.as_i64().and_then(|days| i32::try_from(days).ok()) {
                Some(days) if (1..=366.min(most)).contains(&days) => days,
                _ => {
                    return Err(format!(
                        "annual_commute_days must be a whole number from 1 to {}, not {value}",
                        366.min(most)
                    ));
                }
            },
        };
        let depart_at = clock("depart_at", &self.depart_at, "08:30")?;
        let return_at = clock("return_at", &self.return_at, "17:30")?;
        // Zero-padded HH:MM compares correctly as text.
        if return_at <= depart_at {
            return Err(format!(
                "return_at {return_at} must be later than depart_at {depart_at} on the same day; \
                 overnight schedules are not supported"
            ));
        }
        Ok(Commute {
            entry: point_id("entry_point_id", &self.entry_point_id)?,
            exit: point_id("exit_point_id", &self.exit_point_id)?,
            depart_at,
            return_at,
            isodows,
            annual_days,
        })
    }
}

impl Commute {
    fn schedule(&self) -> Value {
        let weekdays: Vec<&str> = self
            .isodows
            .iter()
            .map(|d| WEEKDAYS[*d as usize - 1])
            .collect();
        json!({
            "depart_at": self.depart_at,
            "return_at": self.return_at,
            "timezone": "America/New_York",
            "weekdays": weekdays,
            "annual_commute_days": self.annual_days,
        })
    }
}

#[derive(Clone)]
struct TollServer {
    app: Arc<App>,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl TollServer {
    fn new(app: Arc<App>) -> Self {
        Self {
            app,
            tool_router: Self::tool_router(),
        }
    }

    #[tool(
        name = "find_toll_ramps",
        description = "Find the toll-road entry and exit ramps for a Northern Virginia trip. Pass the \
            start and end as WGS-84 latitude and longitude in decimal degrees (geocode places first). \
            Returns the best validated route and up to 2 other ramp choices on the same roads, \
            each with entry and exit point IDs, the toll facilities used, a per-facility segment \
            breakdown, and its ordering score. Confirm the chosen option with the user, and use the \
            returned point IDs exactly.",
        annotations(
            title = "Find toll ramps",
            read_only_hint = true,
            idempotent_hint = true
        )
    )]
    async fn find_toll_ramps(
        &self,
        Parameters(request): Parameters<FindTollRamps>,
    ) -> Result<CallToolResult, ErrorData> {
        // A tool error, like rmcp's own argument errors, so the model can correct itself.
        let fix = |message: String| Ok(CallToolResult::error(vec![ContentBlock::text(message)]));
        let ends = position("origin", request.origin)
            .and_then(|origin| Ok((origin, position("destination", request.destination)?)));
        let (origin, destination) = match ends {
            Ok(ends) => ends,
            Err(message) => return fix(message),
        };
        let started = Instant::now();
        let outcome = self.app.find_toll_ramps(origin, destination).await;
        let end = |[lon, lat]: [f64; 2]| json!({ "latitude": lat, "longitude": lon });
        let error = json!({
            "message": "TollChat could not look up ramps right now. Try again later.",
            "origin": end(origin),
            "destination": end(destination),
        });
        Ok(respond("find_toll_ramps", started, outcome, error))
    }

    #[tool(
        name = "estimate_annual_tolls",
        description = "Estimate a commuter's annual tolls, as a ballpark range, for one route option \
            from find_toll_ramps. Pass that option's entry and exit point IDs; TollChat picks the \
            return trip itself. Defaults: leave at 08:30, return at 17:30 (America/New_York), Monday to \
            Friday, 50 weeks a year; override any of them. Prices come from the last 84 days. Returns \
            low, typical, and high annual and daily tolls, not a quote.",
        annotations(
            title = "Estimate annual tolls",
            read_only_hint = true,
            idempotent_hint = true
        )
    )]
    async fn estimate_annual_tolls(
        &self,
        Parameters(request): Parameters<EstimateAnnualTolls>,
    ) -> Result<CallToolResult, ErrorData> {
        let commute = match request.commute() {
            Ok(commute) => commute,
            Err(message) => return Ok(CallToolResult::error(vec![ContentBlock::text(message)])),
        };
        let started = Instant::now();
        let outcome =
            tokio::time::timeout(ESTIMATE_BUDGET, self.app.estimate_annual_tolls(&commute))
                .await
                .unwrap_or_else(|_| Err(Failure::new("estimate", "timeout")));
        let error = json!({
            "message": "TollChat could not estimate tolls right now. Try again later.",
            "schedule": commute.schedule(),
        });
        Ok(respond("estimate_annual_tolls", started, outcome, error))
    }
}

/// Every tool's ending: log the outcome (never its inputs), stamp the time, and return the
/// structured result with a short text summary instead of a JSON copy. `Ok(Err(message))` is an
/// input mistake, returned as a tool error like rmcp's own argument errors so the model can fix it.
fn respond(
    tool: &'static str,
    started: Instant,
    outcome: Result<Result<Value, String>, Failure>,
    mut error: Value,
) -> CallToolResult {
    let (mut value, is_error) = match outcome {
        Ok(Ok(value)) => {
            tracing::info!(
                tool,
                status = value["status"].as_str(),
                elapsed_ms = elapsed_ms(started)
            );
            (value, false)
        }
        Ok(Err(message)) => return CallToolResult::error(vec![ContentBlock::text(message)]),
        Err(failure) => {
            tracing::error!(tool, stage = failure.stage, code = %failure.code, elapsed_ms = elapsed_ms(started));
            error["status"] = json!("error");
            (error, true)
        }
    };
    let now = DateTime::from(SystemTime::now()).fmt(Format::DateTime);
    value["calculated_at"] = json!(now.expect("the current time is a valid RFC 3339 date"));
    let text = vec![ContentBlock::text(summary(&value))];
    let mut result = if is_error {
        CallToolResult::error(text)
    } else {
        CallToolResult::success(text)
    };
    result.structured_content = Some(value);
    result
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for TollServer {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
            .with_server_info(Implementation::new("tollchat", env!("CARGO_PKG_VERSION")))
            .with_instructions(INSTRUCTIONS)
    }
}

fn elapsed_ms(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX)
}

/// One end of the trip as [lon, lat], used at full precision, or a message saying what to fix.
fn position(side: &str, value: Value) -> Result<[f64; 2], String> {
    // Never positional: a bare pair could be [lon, lat] or [lat, lon].
    let Some(fields) = value.as_object() else {
        return Err(format!(
            "{side} must be an object with named latitude and longitude fields, \
             for example {{\"latitude\": 38.96, \"longitude\": -77.36}}"
        ));
    };
    if let Some(extra) = fields
        .keys()
        .find(|k| !["latitude", "longitude"].contains(&k.as_str()))
    {
        return Err(format!(
            "{side}.{extra} is not accepted; send only latitude and longitude"
        ));
    }
    let degrees = |field: &str, limit: f64| {
        let value = fields
            .get(field)
            .ok_or_else(|| format!("{side}.{field} is missing"))?;
        let degrees = value
            .as_f64()
            .ok_or_else(|| format!("{side}.{field} must be a number, not {value}"))?;
        if degrees.abs() > limit {
            return Err(format!(
                "{side}.{field} {degrees} is outside -{limit} to {limit}"
            ));
        }
        Ok(degrees)
    };
    let latitude = degrees("latitude", 90.0)?;
    Ok([degrees("longitude", 180.0)?, latitude])
}

/// One line for people; the structured result carries everything.
fn summary(value: &Value) -> String {
    let status = value["status"].as_str().unwrap_or_default();
    let text = |value: &Value| value.as_str().unwrap_or_default().to_owned();
    match value["options"].as_array().map(Vec::as_slice) {
        Some([best, ..]) => format!(
            "{status}: {count} option(s). Best: enter at {entry} ({entry_id}), exit at {exit} \
             ({exit_id}), via {facilities}. Full details are in the structured result.",
            count = value["options"].as_array().map_or(0, Vec::len),
            entry = text(&best["entry"]["label"]),
            entry_id = text(&best["entry"]["point_id"]),
            exit = text(&best["exit"]["label"]),
            exit_id = text(&best["exit"]["point_id"]),
            facilities = best["facilities"]
                .as_array()
                .map(|codes| codes.iter().map(text).collect::<Vec<_>>().join(", "))
                .unwrap_or_default(),
        ),
        _ if value["status"] == "estimated" => {
            let dollars = |level: &str| {
                let amount = value["annual_toll_usd"][level].as_f64().unwrap_or_default();
                format!("${amount:.0}")
            };
            format!(
                "{status}: about {} a year in tolls (range {} to {}), from {} of {} recent \
                 commute days. Full details are in the structured result.",
                dollars("typical"),
                dollars("low"),
                dollars("high"),
                value["basis"]["priced_days"],
                value["basis"]["eligible_days"],
            )
        }
        _ => match value["message"].as_str() {
            Some(message) => format!("{status}: {message}"),
            None => {
                format!("{status}: no route options. Full details are in the structured result.")
            }
        },
    }
}

/// An internal failure, logged by stage and service code only (never message text).
struct Failure {
    stage: &'static str,
    code: String,
}

impl Failure {
    fn new(stage: &'static str, code: impl Into<String>) -> Self {
        Self {
            stage,
            code: code.into(),
        }
    }

    fn database(stage: &'static str, error: &BoxError) -> Self {
        let code = error
            .downcast_ref::<tokio_postgres::Error>()
            .and_then(tokio_postgres::Error::code)
            .map_or("unavailable", |state| state.code());
        Self::new(stage, code)
    }
}

#[derive(Deserialize)]
struct Point {
    point_id: String,
    network_id: String,
    point_type: String,
    direction: Option<String>,
    label: String,
    location: Option<GeoPoint>,
}

#[derive(Deserialize)]
struct GeoPoint {
    coordinates: [f64; 2],
}

struct Candidate<'a> {
    point: &'a Point,
    miles: f64,
}

impl App {
    /// `Ok(Err(message))` is an input mistake the caller should fix.
    async fn find_toll_ramps(
        &self,
        origin: [f64; 2],
        destination: [f64; 2],
    ) -> Result<Result<Value, String>, Failure> {
        let points = self.load_points().await?;
        let origins = candidates_near(&points, origin, "entry");
        let destinations = candidates_near(&points, destination, "exit");
        for (side, [lon, lat], role, candidates) in [
            ("origin", origin, "entry", &origins),
            ("destination", destination, "exit", &destinations),
        ] {
            // A Virginia longitude given as latitude lands in Antarctica; swapped back, it is covered.
            if candidates.is_empty() && !candidates_near(&points, [lat, lon], role).is_empty() {
                return Ok(Err(format!(
                    "{side}.latitude {lat} is outside the plausible range for this service; \
                     did you swap latitude and longitude?"
                )));
            }
        }

        let end = |[lon, lat]: [f64; 2], candidates: &[Candidate<'_>]| {
            let coverage = if candidates.is_empty() {
                "outside_coverage"
            } else {
                "covered"
            };
            json!({ "latitude": lat, "longitude": lon, "coverage": coverage })
        };
        let mut response = json!({
            "origin": end(origin, &origins),
            "destination": end(destination, &destinations),
        });
        let (status, options) = if origins.is_empty() || destinations.is_empty() {
            ("outside_coverage", Vec::new())
        } else if miles(origin, destination) < SAME_LOCATION_MILES {
            ("same_location", Vec::new())
        } else {
            self.validated_options(&points, &origins, &destinations)
                .await?
        };
        response["status"] = json!(status);
        response["options"] = json!(options);
        Ok(Ok(response))
    }

    async fn load_points(&self) -> Result<Vec<Point>, Failure> {
        let fail = |error: BoxError| Failure::database("load_points", &error);
        let client = (self.database.connect)(self.database.points_role.clone())
            .await
            .map_err(fail)?;
        let row = client
            .query_one(POINTS_SQL, &[])
            .await
            .map_err(|e| fail(e.into()))?;
        // shortcut: reads the agent's prompt-point surface; give MCP its own catalog function once shapes diverge.
        serde_json::from_value(row.get::<_, Value>("points"))
            .map_err(|_| Failure::new("load_points", "shape"))
    }

    /// Every option is validated with the pricing tools' own route check before it is returned.
    /// Routes are chosen as the estimate prices them, without today's reversible-lane state, so the
    /// answer does not change with the time of day; each option only says whether it is usable now.
    async fn validated_options(
        &self,
        points: &[Point],
        origins: &[Candidate<'_>],
        destinations: &[Candidate<'_>],
    ) -> Result<(&'static str, Vec<Value>), Failure> {
        let fail = |error: BoxError| Failure::database("validate_routes", &error);
        let ids = |side: &[Candidate<'_>]| {
            side.iter()
                .map(|c| c.point.point_id.clone())
                .collect::<Vec<_>>()
        };
        let client = (self.database.connect)(self.database.pricing_role.clone())
            .await
            .map_err(fail)?;
        let rows = client
            .query(ROUTES_SQL, &[&ids(origins), &ids(destinations)])
            .await
            .map_err(|e| fail(e.into()))?;

        // One lane state per query, so any route's evidence gives the direction.
        let lanes_now = rows
            .iter()
            .find_map(|row| row.get::<_, Option<Value>>("i95_evidence"))
            .map_or(json!("unknown"), |evidence| {
                evidence["availability"].clone()
            });
        let mut ranked = Vec::new();
        for row in &rows {
            let legs: Value = row.get("facility_legs");
            let (Some(entry), Some(exit)) = (
                find(origins, row.get("origin")),
                find(destinations, row.get("destination")),
            ) else {
                continue;
            };
            let facilities = facilities(&legs);
            if row.get::<_, &str>("status") != "valid" || facilities.is_empty() {
                continue;
            }
            let point_ids: Vec<String> = row.get("point_ids");
            let evidence: Option<Value> = row.get("i95_evidence");
            // The live check routes around lanes running the wrong way, so if it found another route
            // for this pair, this one needs the lanes and is not usable now.
            let usable_now = if row.get::<_, Vec<String>>("live_point_ids") != point_ids {
                Some((lanes_now != "unknown").then_some(false))
            } else {
                evidence
                    .as_ref()
                    .map(|_| match row.get::<_, &str>("live_status") {
                        "valid" => Some(true),
                        "unknown_availability" => None,
                        _ => Some(false),
                    })
            };
            // Present only for routes whose use depends on the I-95/I-395 reversible lanes.
            let lanes = usable_now.map(|usable_now| {
                let direction = evidence.map_or(lanes_now.clone(), |e| e["availability"].clone());
                json!({ "direction": direction, "usable_now": usable_now })
            });
            let (segments, toll_miles) = segments(points, &legs)?;
            let score = score(entry, exit, &facilities, toll_miles);
            let roads = roads(points, &point_ids);
            ranked.push((
                score, entry, exit, facilities, segments, toll_miles, roads, lanes,
            ));
        }
        // Equal scores are common (one interchange, two exits); break ties the same way every time.
        let key = |c: &Candidate<'_>| c.point.point_id.clone();
        ranked.sort_by(|a, b| {
            (a.0.total_cmp(&b.0)).then_with(|| (key(a.1), key(a.2)).cmp(&(key(b.1), key(b.2))))
        });

        // One path per answer: the best route, and other ramps onto the same roads in the same
        // direction, never a second way around (I-495 and I-66 when I-395 goes there directly).
        let best_roads = ranked.first().map(|best| best.6.clone());
        // Approach variants of one interchange validate separately; show each route once.
        let mut seen = Vec::new();
        let mut options = Vec::new();
        for (score, entry, exit, facilities, segments, toll_miles, roads, lanes) in ranked {
            let route = (spot(entry.point), spot(exit.point), facilities.clone());
            if options.len() == MAX_OPTIONS
                || Some(&roads) != best_roads.as_ref()
                || seen.contains(&route)
            {
                continue;
            }
            seen.push(route);
            let access = entry.miles + exit.miles;
            let mut option = json!({
                "route_id": route_id(&entry.point.point_id, &segments, &exit.point.point_id),
                "entry": entry.point.describe(),
                "exit": exit.point.describe(),
                "facilities": facilities,
                "segments": segments,
                "total_straight_line_miles": round_tenth(toll_miles),
                "access_miles": { "origin": round_tenth(entry.miles), "destination": round_tenth(exit.miles) },
                "score": {
                    "access_miles": round_tenth(access),
                    "toll_miles": round_tenth(TOLL_MILE_WEIGHT * toll_miles),
                    "facility_penalty_miles": round_tenth(penalty(&facilities)),
                    "total": round_tenth(score),
                },
            });
            if let Some(lanes) = lanes {
                option["reversible_lanes"] = lanes;
            }
            options.push(option);
        }
        let status = if options.is_empty() {
            "no_valid_route"
        } else {
            "resolved"
        };
        Ok((status, options))
    }

    /// `Ok(Err(message))` is an input mistake the caller should fix.
    async fn estimate_annual_tolls(
        &self,
        commute: &Commute,
    ) -> Result<Result<Value, String>, Failure> {
        let points = self.load_points().await?;
        let point = |field: &str, id: &str, role: &str| {
            let point = points
                .iter()
                .find(|p| p.point_id == id && p.location.is_some())
                .ok_or_else(|| {
                    format!("{field} {id} is not a TollChat point; use an ID from find_toll_ramps")
                })?;
            if point.point_type == role || point.point_type == "airport" {
                Ok(point)
            } else {
                Err(format!(
                    "{field} {id} is an {} point, not an {role} point",
                    point.point_type
                ))
            }
        };
        let ends = point("entry_point_id", &commute.entry, "entry")
            .and_then(|entry| Ok((entry, point("exit_point_id", &commute.exit, "exit")?)));
        let (entry, exit) = match ends {
            Ok(ends) => ends,
            Err(message) => return Ok(Err(message)),
        };

        let fail = |stage| move |error: BoxError| Failure::database(stage, &error);
        let mut client = (self.database.connect)(self.database.pricing_role.clone())
            .await
            .map_err(fail("estimate_connect"))?;
        // One transaction: the oracle checks that its sample window ends at this transaction's start.
        let transaction = client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(|e| fail("estimate_connect")(e.into()))?;
        transaction
            .batch_execute(BALLPARK_TIMEOUT_SQL)
            .await
            .map_err(|e| fail("estimate_connect")(e.into()))?;
        let query = |stage, rows: Result<Vec<tokio_postgres::Row>, tokio_postgres::Error>| {
            rows.map_err(|e| fail(stage)(e.into()))
        };

        let outbound = query(
            "estimate_routes",
            transaction
                .query(
                    BALLPARK_ROUTES_SQL,
                    &[&vec![&entry.point_id], &vec![&exit.point_id]],
                )
                .await,
        )?;
        let status: String = outbound
            .first()
            .map(|row| row.get("status"))
            .unwrap_or_default();
        let outbound_legs: Value = outbound
            .first()
            .map(|row| row.get("facility_legs"))
            .unwrap_or_default();
        // find_toll_ramps never offers a toll-free route, so one here was not taken from it.
        if status != "valid" || facilities(&outbound_legs).is_empty() {
            return Ok(Err(format!(
                "{} to {} is not a toll route TollChat can price ({status}); pass the entry and exit \
                 of one find_toll_ramps option",
                entry.point_id, exit.point_id
            )));
        }
        let mut response = json!({
            "schedule": commute.schedule(),
            "outbound": priced_route(&points, entry, exit, &outbound_legs)?,
        });

        // The way back starts near the outbound exit and ends near its entry. The exact ramps barely
        // change the price, but a different road can, so routes over the same roads (by the
        // networks they pass through, tolled or not) come first.
        let location = |point: &Point| point.location.as_ref().map(|l| l.coordinates);
        let (Some(from), Some(to)) = (location(exit), location(entry)) else {
            return Err(Failure::new("estimate_routes", "shape"));
        };
        let (starts, finishes) = (
            return_candidates(&points, from, "entry"),
            return_candidates(&points, to, "exit"),
        );
        let ids = |side: &[Candidate<'_>]| {
            side.iter()
                .map(|c| c.point.point_id.clone())
                .collect::<Vec<_>>()
        };
        let rows = query(
            "estimate_routes",
            transaction
                .query(BALLPARK_ROUTES_SQL, &[&ids(&starts), &ids(&finishes)])
                .await,
        )?;
        let outbound_ids: Vec<String> = outbound
            .first()
            .map(|row| row.get("point_ids"))
            .unwrap_or_default();
        let mut same_roads = networks(&points, &outbound_ids);
        same_roads.reverse();
        let mut back = Vec::new();
        for row in rows
            .iter()
            .filter(|row| row.get::<_, &str>("status") == "valid")
        {
            let (Some(start), Some(finish)) = (
                find(&starts, row.get("origin")),
                find(&finishes, row.get("destination")),
            ) else {
                continue;
            };
            let legs: Value = row.get("facility_legs");
            let score = score(
                start,
                finish,
                &facilities(&legs),
                segments(&points, &legs)?.1,
            );
            let roads = networks(&points, &row.get::<_, Vec<String>>("point_ids"));
            back.push((roads != same_roads, score, start, finish, legs));
        }
        let back = back.into_iter().min_by(|a, b| {
            (a.0.cmp(&b.0)).then(a.1.total_cmp(&b.1)).then_with(|| {
                (&a.2.point.point_id, &a.3.point.point_id)
                    .cmp(&(&b.2.point.point_id, &b.3.point.point_id))
            })
        });
        let Some((_, _, start, finish, return_legs)) = back else {
            response["status"] = json!("no_return_route");
            response["message"] =
                json!("TollChat found no toll route back near the outbound ramps.");
            return Ok(Ok(response));
        };
        response["return"] = priced_route(&points, start.point, finish.point, &return_legs)?;

        let days = query(
            "estimate_days",
            transaction
                .query(SAMPLE_DAYS_SQL, &[&commute.isodows])
                .await,
        )?;
        let (mut legs, mut fixed_prices) = (Vec::new(), Vec::new());
        for (direction, route_legs, wall_time) in [
            ("outbound", &outbound_legs, &commute.depart_at),
            ("return", &return_legs, &commute.return_at),
        ] {
            for leg in route_legs.as_array().into_iter().flatten() {
                let (facility, key) = (
                    leg["facility"].as_str().unwrap_or_default(),
                    &leg["pricing_key"],
                );
                let mut item = json!({ "direction": direction, "facility": facility, "route_step_id": leg["route_step_id"] });
                match facility {
                    "i66" => {
                        item["start_zone_id"] = key["start_zone_id"].clone();
                        item["end_zone_id"] = key["end_zone_id"].clone();
                    }
                    "i95_i495" => item["od_pair_id"] = key["od_pair_id"].clone(),
                    // Published rates: one price for every sampled day.
                    _ => {
                        for day in &days {
                            let price = fixed_price(
                                facility,
                                key["source_route_key"].as_str().unwrap_or_default(),
                                key["charge_index"].as_u64().unwrap_or_default(),
                                day.get::<_, i32>("isodow"),
                                wall_time,
                            )
                            .ok_or_else(|| Failure::new("estimate_fixed_prices", "shape"))?;
                            fixed_prices.push(json!({
                                "sample_date": day.get::<_, &str>("day"),
                                "direction": direction,
                                "route_step_id": leg["route_step_id"],
                                "price_usd": price,
                            }));
                        }
                    }
                }
                legs.push(item);
            }
        }

        let sample_days: Vec<&str> = days.iter().map(|day| day.get("day")).collect();
        let summary = query(
            "estimate_prices",
            transaction
                .query(
                    BALLPARK_SQL,
                    &[
                        &json!(legs),
                        &commute.depart_at,
                        &commute.return_at,
                        &sample_days,
                        &json!(fixed_prices),
                        &commute.annual_days,
                    ],
                )
                .await,
        )?;
        let summary = summary
            .first()
            .ok_or_else(|| Failure::new("estimate_prices", "shape"))?;
        let priced_days: i32 = summary.get("complete_pair_count");
        let eligible_days: i32 = summary.get("eligible_date_count");
        let (window_start, window_end): (&str, &str) = days
            .first()
            .map(|day| (day.get("window_start"), day.get("window_end")))
            .unwrap_or_default();
        let by_weekday: Vec<Value> = summary
            .get::<_, Value>("coverage_by_weekday")
            .as_array()
            .into_iter()
            .flatten()
            .map(|day| {
                let isodow = day["sample_isodow"].as_u64().unwrap_or_default() as usize;
                json!({
                    "weekday": WEEKDAYS.get(isodow.wrapping_sub(1)),
                    "eligible_days": day["eligible_date_count"],
                    "priced_days": day["complete_pair_count"],
                })
            })
            .collect();
        response["basis"] = json!({
            "method": "recent_complete_same_date_round_trips",
            "window": { "start_date": window_start, "end_date": window_end },
            "eligible_days": eligible_days,
            "priced_days": priced_days,
            "coverage_percent": summary.get::<_, &str>("coverage_percent").parse::<f64>().ok(),
            "coverage_by_weekday": by_weekday,
            "sample_status": summary.get::<_, &str>("sample_status"),
            "uses_modeled_prices": summary.get::<_, bool>("uses_modeled"),
            "uses_published_fixed_rates": summary.get::<_, bool>("uses_current_fixed_rates"),
        });
        // An I-95/I-495 leg needs feed data on every day, so its gaps drop days at random: they
        // thin the sample without biasing it, and the estimate uses whatever days are priced.
        // Without one, I-66 prices its toll-free weekends and holidays at $0 even with no data, so
        // gaps drop only tolled days; those routes need half of each weekday's days priced.
        let gaps_are_random = legs.iter().any(|leg| leg["facility"] == "i95_i495");
        let thin: Vec<String> = by_weekday
            .iter()
            .filter(|day| {
                let priced = day["priced_days"].as_i64().unwrap_or_default();
                let eligible = day["eligible_days"].as_i64().unwrap_or_default();
                if gaps_are_random {
                    priced < MIN_PRICED_PER_WEEKDAY
                } else {
                    2 * priced < eligible
                }
            })
            .filter_map(|day| day["weekday"].as_str().map(|name| format!("{name}s")))
            .collect();
        if !thin.is_empty() || (gaps_are_random && 4 * priced_days < eligible_days) {
            let weekdays = if thin.is_empty() {
                String::new()
            } else {
                format!(", too few {}", thin.join(", "))
            };
            let needed = if gaps_are_random {
                "at least two of each commute weekday and a quarter of all days"
            } else {
                "at least half of each commute weekday's days"
            };
            response["status"] = json!("too_few_recent_prices");
            response["message"] = json!(format!(
                "Only {priced_days} of {eligible_days} recent commute days had prices for every \
                 toll on both trips at these times{weekdays}; TollChat needs {needed} for an \
                 estimate."
            ));
            return Ok(Ok(response));
        }
        let usd = |column: &str| {
            summary
                .get::<_, Option<&str>>(column)
                .and_then(|text| text.parse::<f64>().ok())
        };
        let range = |prefix: &str| {
            json!({
                "low": usd(&format!("{prefix}_low")),
                "typical": usd(&format!("{prefix}_typical")),
                "high": usd(&format!("{prefix}_high")),
            })
        };
        let by_facility: Vec<Value> = summary
            .get::<_, Value>("facility_scenarios")
            .as_array()
            .into_iter()
            .flatten()
            .map(|facility| {
                let annual = |pct: &str| {
                    facility["scenarios"][pct]["annualized_usd"]
                        .as_str()
                        .and_then(|text| text.parse::<f64>().ok())
                };
                json!({
                    "facility": facility["facility"],
                    "annual_toll_usd": { "low": annual("p25"), "typical": annual("p50"), "high": annual("p90") },
                    "priced_days": facility["sample_count"],
                })
            })
            .collect();
        response["status"] = json!("estimated");
        response["annual_toll_usd"] = range("annual");
        response["daily_round_trip_usd"] = range("daily");
        response["by_facility"] = json!(by_facility);
        Ok(Ok(response))
    }
}

/// A priced route as callers see it: the same fields as a find_toll_ramps option's ends.
fn priced_route(
    points: &[Point],
    entry: &Point,
    exit: &Point,
    legs: &Value,
) -> Result<Value, Failure> {
    let (segments, _) = segments(points, legs)?;
    Ok(json!({
        "route_id": route_id(&entry.point_id, &segments, &exit.point_id),
        "entry": entry.describe(),
        "exit": exit.describe(),
        "facilities": facilities(legs),
    }))
}

/// The toll facilities of a route's priced legs, in travel order.
fn facilities(legs: &Value) -> Vec<String> {
    let mut facilities: Vec<String> = legs
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|leg| leg["facility"].as_str().map(str::to_owned))
        .collect();
    facilities.dedup();
    facilities
}

/// The trip's straight-line length, with toll miles counted at half (express lanes run about twice
/// as fast as the local roads to the ramps) and each toll facility after the first as extra miles:
/// the quicker trip on fewer toll roads ranks first.
fn score(
    entry: &Candidate<'_>,
    exit: &Candidate<'_>,
    facilities: &[String],
    toll_miles: f64,
) -> f64 {
    // shortcut: straight-line miles, not drive time; upgrade to a Routes matrix if users get cross-river picks.
    entry.miles + exit.miles + TOLL_MILE_WEIGHT * toll_miles + penalty(facilities)
}

fn penalty(facilities: &[String]) -> f64 {
    FACILITY_PENALTY_MILES * facilities.len().saturating_sub(1) as f64
}

/// One Dulles Toll Road or Greenway charge at the published rate, as dollars text, for a leg's
/// `source_route_key` and `charge_index` at an ISO weekday and HH:MM America/New_York time.
/// Public so the e2e suite can check it against every charge in the oracle catalog.
///
/// shortcut: rules and rates copied from `v2/agent_tools/current_price_domain.py`
/// (`price_dtr_leg`, `price_greenway_leg`); update both when the operators change rates. Unlike
/// that code it does not skip DST-ambiguous times, which only matters 1-3 AM on two days a year.
pub fn fixed_price(
    facility: &str,
    route_key: &str,
    charge_index: u64,
    isodow: i32,
    wall_time: &str,
) -> Option<&'static str> {
    const DTR_EXITS: [&str; 11] = [
        "28", "10", "11", "12", "13", "14", "15", "16", "17", "1819", "66",
    ];
    const DTR_RAMPS: [&str; 6] = ["10", "11", "12", "13", "14", "17"];
    // The $2 connection charge between the Greenway and the Dulles Toll Road at Route 28.
    if facility == "dtr" && matches!(route_key, "greenway_to_dtr" | "dtr_to_greenway") {
        return (charge_index == 1).then_some("2.00");
    }
    let mut parts = route_key.split(':');
    let (Some(direction), Some(entry), Some(exit), None) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return None;
    };
    match facility {
        "dtr" => {
            let position = |exit: &str| DTR_EXITS.iter().position(|e| *e == exit);
            let (from, to, plaza) = (position(entry)?, position(exit)?, position("16")?);
            // In travel order: an entrance ramp, the main plaza if passed, an exit ramp.
            let mut charges = Vec::new();
            if DTR_RAMPS.contains(&entry) {
                charges.push("2.00");
            }
            if from.min(to) <= plaza && plaza < from.max(to) {
                charges.push("4.00");
            }
            if DTR_RAMPS.contains(&exit) || (direction == "EB" && exit == "16") {
                charges.push("2.00");
            }
            charges
                .get(usize::try_from(charge_index).ok()?.checked_sub(1)?)
                .copied()
        }
        "greenway" => {
            // Peak: weekday mornings eastbound, weekday evenings westbound (HH:MM compares as text).
            let peak = isodow <= 5
                && match direction {
                    "EB" => ("06:30".."09:00").contains(&wall_time),
                    "WB" => ("16:00".."18:30").contains(&wall_time),
                    _ => false,
                };
            let main_plaza = entry == "28" || exit == "28";
            (charge_index == 1).then_some(match (main_plaza, peak) {
                (false, false) => "4.55",
                (false, true) => "5.10",
                (true, false) => "5.25",
                (true, true) => "5.80",
            })
        }
        _ => None,
    }
}

impl Point {
    /// The catalog fields a caller needs; airports have no direction, so theirs is left out.
    fn describe(&self) -> Value {
        let mut point = json!({
            "point_id": self.point_id,
            "network": self.network_id,
            "role": self.point_type,
            "label": self.label,
        });
        if let Some(direction) = &self.direction {
            point["direction"] = json!(direction);
        }
        point
    }
}

/// One segment per stretch of toll road, with the straight-line distance between its ends (the
/// catalog has no road miles) and the pricing key of every toll charged on it.
fn segments(points: &[Point], legs: &Value) -> Result<(Vec<Value>, f64), Failure> {
    let located = |id: &Value| {
        let point = points.iter().find(|p| id.as_str() == Some(&p.point_id))?;
        Some(point.location.as_ref()?.coordinates)
    };
    let mut total = 0.0;
    let mut segments: Vec<Value> = Vec::new();
    for leg in legs.as_array().into_iter().flatten() {
        let (from, to) = (&leg["point_ids"][0], &leg["point_ids"][1]);
        // The Dulles Toll Road and Greenway can charge twice for one stretch, as separate legs.
        if let Some(same) = segments.last_mut().filter(|segment| {
            segment["facility"] == leg["facility"]
                && segment["entry_point_id"] == *from
                && segment["exit_point_id"] == *to
        }) {
            if let Some(keys) = same["pricing_keys"].as_array_mut() {
                keys.push(leg["pricing_key"].clone());
            }
            continue;
        }
        let (Some(a), Some(b)) = (located(from), located(to)) else {
            return Err(Failure::new("segments", "shape"));
        };
        total += miles(a, b);
        segments.push(json!({
            "facility": leg["facility"],
            "entry_point_id": from,
            "exit_point_id": to,
            "straight_line_miles": round_tenth(miles(a, b)),
            "pricing_keys": [leg["pricing_key"]],
        }));
    }
    Ok((segments, total))
}

/// The entry, each toll segment's ends, and the exit, joined by `>`, so the same ID always means
/// the same route.
fn route_id(entry: &str, segments: &[Value], exit: &str) -> String {
    let mut chain = vec![entry];
    let ends = segments
        .iter()
        .flat_map(|s| [&s["entry_point_id"], &s["exit_point_id"]])
        .filter_map(Value::as_str);
    for id in ends.chain([exit]) {
        if chain.last() != Some(&id) {
            chain.push(id);
        }
    }
    chain.join(">")
}

fn find<'s, 'a>(side: &'s [Candidate<'a>], id: &str) -> Option<&'s Candidate<'a>> {
    side.iter().find(|c| c.point.point_id == id)
}

/// Where a point sits, comparable exactly.
fn spot(point: &Point) -> Option<[u64; 2]> {
    let [lon, lat] = point.location.as_ref()?.coordinates;
    Some([lon.to_bits(), lat.to_bits()])
}

/// Whether a point can serve this side's role (`entry` or `exit`) at this distance.
fn fits(point: &Point, role: &str, distance: f64, radius: f64) -> bool {
    match point.point_type.as_str() {
        // An airport is a candidate only for a trip that starts or ends at that airport.
        "airport" => distance <= AIRPORT_MATCH_MILES,
        kind => kind == role && distance <= radius,
    }
}

/// Ramps for the way back: the nearest per road, as for a trip, plus every ramp close by.
fn return_candidates<'a>(points: &'a [Point], at: [f64; 2], role: &str) -> Vec<Candidate<'a>> {
    let mut candidates = candidates_near(points, at, role);
    for point in points {
        let Some(location) = &point.location else {
            continue;
        };
        let distance = miles(at, location.coordinates);
        if fits(point, role, distance, RETURN_SEARCH_MILES)
            && find(&candidates, &point.point_id).is_none()
        {
            candidates.push(Candidate {
                point,
                miles: distance,
            });
        }
    }
    candidates
}

/// The roads a route passes through, tolled or not, as (network, direction) in order, from its
/// walked point IDs.
fn roads<'a>(points: &'a [Point], ids: &[String]) -> Vec<(&'a str, Option<&'a str>)> {
    let mut roads: Vec<_> = ids
        .iter()
        .filter_map(|id| points.iter().find(|p| &p.point_id == id))
        .map(|p| (p.network_id.as_str(), p.direction.as_deref()))
        .collect();
    roads.dedup();
    roads
}

/// The networks a route passes through, in order, whatever the direction.
fn networks<'a>(points: &'a [Point], ids: &[String]) -> Vec<&'a str> {
    let mut networks: Vec<&str> = roads(points, ids).into_iter().map(|(n, _)| n).collect();
    networks.dedup();
    networks
}

/// The nearest interchange per (facility, direction) for this side's role, within reach.
fn candidates_near<'a>(points: &'a [Point], at: [f64; 2], role: &str) -> Vec<Candidate<'a>> {
    let reachable: Vec<Candidate<'a>> = points
        .iter()
        .filter_map(|point| {
            let distance = miles(at, point.location.as_ref()?.coordinates);
            fits(point, role, distance, MAX_ACCESS_MILES).then_some(Candidate {
                point,
                miles: distance,
            })
        })
        .collect();
    let mut nearest: BTreeMap<(&str, Option<&str>), f64> = BTreeMap::new();
    for candidate in &reachable {
        let group = (
            candidate.point.network_id.as_str(),
            candidate.point.direction.as_deref(),
        );
        let best = nearest.entry(group).or_insert(candidate.miles);
        *best = best.min(candidate.miles);
    }
    let mut groups: Vec<_> = nearest.into_iter().collect();
    groups.sort_by(|a, b| a.1.total_cmp(&b.1));
    groups.truncate(MAX_GROUPS_PER_SIDE);
    reachable
        .into_iter()
        .filter(|candidate| {
            let group = (
                candidate.point.network_id.as_str(),
                candidate.point.direction.as_deref(),
            );
            groups
                .iter()
                .any(|(g, best)| *g == group && candidate.miles <= best + SAME_INTERCHANGE_MILES)
        })
        .collect()
}

/// Great-circle distance in miles between two [lon, lat] positions.
fn miles(a: [f64; 2], b: [f64; 2]) -> f64 {
    let (lat1, lat2) = (a[1].to_radians(), b[1].to_radians());
    let half_dlat = (lat2 - lat1) / 2.0;
    let half_dlon = (b[0] - a[0]).to_radians() / 2.0;
    let h = half_dlat.sin().powi(2) + lat1.cos() * lat2.cos() * half_dlon.sin().powi(2);
    2.0 * 3_958.8 * h.sqrt().asin()
}

fn round_tenth(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}
