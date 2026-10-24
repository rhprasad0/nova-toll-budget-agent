//! TollChat MCP server: Muse-facing toll tools over the TollChat routing oracle.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use aws_credential_types::provider::{ProvideCredentials, SharedCredentialsProvider};
use aws_sdk_dynamodb::operation::update_item::UpdateItemError;
use aws_sdk_dynamodb::types::AttributeValue;
use aws_sdk_geoplaces::types::{SearchTextFilter, SearchTextIntendedUse};
use aws_sigv4::http_request::{
    SignableBody, SignableRequest, SignatureLocation, SigningSettings, sign,
};
use aws_sigv4::sign::v4;
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

const DAILY_LOOKUP_LIMIT: u64 = 1_000;
const LOOKUPS_PER_CALL: u64 = 2;
/// Fairfax, the middle of the covered network, as [lon, lat].
const SERVICE_AREA_CENTER: [f64; 2] = [-77.30, 38.88];
const MAX_ACCESS_MILES: f64 = 8.0;
const AIRPORT_MATCH_MILES: f64 = 1.5;
const AMBIGUOUS_MILES: f64 = 2.0;
/// Approach variants of one interchange share a spot; keep them together.
const SAME_INTERCHANGE_MILES: f64 = 0.1;
const MAX_GROUPS_PER_SIDE: usize = 4;
const MAX_OPTIONS: usize = 3;
const MAX_PLACE_CHARS: usize = 200;

const POINTS_SQL: &str = "SELECT oracle.get_toll_route_prompt_points() AS points";
const VALIDATE_SQL: &str = "SELECT o.id AS origin, d.id AS destination, route.status, route.facility_legs \
     FROM unnest($1::text[]) AS o(id) CROSS JOIN unnest($2::text[]) AS d(id) \
     CROSS JOIN LATERAL oracle.validate_pricing_route(o.id, d.id) AS route";

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
    pub places: aws_sdk_geoplaces::Client,
    pub dynamodb: aws_sdk_dynamodb::Client,
    pub lookup_table: String,
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

#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
struct FindTollRamps {
    /// Where the trip starts, as the user described it: a landmark, neighborhood, town, or
    /// nearby intersection. An exact home address is not needed.
    #[schemars(length(min = 1, max = 200))]
    origin: String,
    /// Where the trip ends, described the same way.
    #[schemars(length(min = 1, max = 200))]
    destination: String,
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
            start and end places as the user described them. Returns up to 3 validated route options, \
            each with an entry point ID, an exit point ID, the toll facilities used, and straight-line \
            access miles. Confirm the matched places and the chosen option with the user, and use the \
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
        let (origin, destination) = (request.origin.trim(), request.destination.trim());
        for place in [origin, destination] {
            if place.is_empty() || place.chars().count() > MAX_PLACE_CHARS {
                // A tool error, like rmcp's own argument errors, so the model can correct itself.
                return Ok(CallToolResult::error(vec![ContentBlock::text(
                    "origin and destination must each be 1 to 200 characters",
                )]));
            }
        }
        let started = Instant::now();
        let result = match self.app.find_toll_ramps(origin, destination).await {
            Ok(value) => {
                tracing::info!(
                    tool = "find_toll_ramps",
                    status = value["status"].as_str(),
                    elapsed_ms = elapsed_ms(started)
                );
                CallToolResult::structured(value)
            }
            Err(failure) => {
                tracing::error!(tool = "find_toll_ramps", stage = failure.stage, code = %failure.code, elapsed_ms = elapsed_ms(started));
                CallToolResult::structured_error(json!({
                    "status": "error",
                    "message": "TollChat could not look up ramps right now. Try again later.",
                }))
            }
        };
        Ok(result)
    }
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

struct Place {
    name: String,
    address: Option<String>,
    position: [f64; 2],
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
    async fn find_toll_ramps(&self, origin: &str, destination: &str) -> Result<Value, Failure> {
        if !self.reserve_lookups().await? {
            return Ok(json!({
                "status": "daily_lookup_limit",
                "message": "TollChat's daily place-lookup limit is used up. Try again after midnight UTC.",
            }));
        }
        let (origin_places, destination_places) =
            tokio::try_join!(self.search(origin), self.search(destination))?;

        let mut response = json!({ "status": "resolved" });
        let mut positions = Vec::new();
        for (side, places) in [
            ("origin", &origin_places),
            ("destination", &destination_places),
        ] {
            response[side] = match places.as_slice() {
                [] => json!({ "match": "place_not_found" }),
                [top, rest @ ..]
                    if rest
                        .iter()
                        .any(|other| miles(top.position, other.position) > AMBIGUOUS_MILES) =>
                {
                    json!({ "match": "ambiguous", "candidates": places.iter().map(Place::label).collect::<Vec<_>>() })
                }
                [top, ..] => {
                    positions.push(top.position);
                    json!({ "match": "resolved", "name": top.name, "address": top.address })
                }
            };
        }
        if let [origin_at, destination_at] = positions[..] {
            let points = self.load_points().await?;
            let origins = candidates_near(&points, origin_at, "entry");
            let destinations = candidates_near(&points, destination_at, "exit");
            for (side, found) in [("origin", &origins), ("destination", &destinations)] {
                if found.is_empty() {
                    response[side]["match"] = json!("outside_coverage");
                }
            }
            if !origins.is_empty() && !destinations.is_empty() {
                let (status, options) = self.validated_options(&origins, &destinations).await?;
                response["status"] = json!(status);
                response["options"] = json!(options);
                return Ok(response);
            }
        }
        // Report the first side that needs attention; both sides' details are included.
        let problem = ["origin", "destination"]
            .iter()
            .map(|side| response[*side]["match"].clone())
            .find(|m| m != "resolved");
        response["status"] = problem.unwrap_or_else(|| json!("error"));
        Ok(response)
    }

    /// Reserve this call's lookups against the shared UTC-day budget before spending any.
    async fn reserve_lookups(&self) -> Result<bool, Failure> {
        let day = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
            / 86_400;
        let number = |value: u64| AttributeValue::N(value.to_string());
        let reserved = self
            .dynamodb
            .update_item()
            .table_name(&self.lookup_table)
            .key("day", number(day))
            .update_expression("ADD lookups :count SET expires_at = :expires")
            .condition_expression("attribute_not_exists(lookups) OR lookups <= :last_start")
            .expression_attribute_values(":count", number(LOOKUPS_PER_CALL))
            .expression_attribute_values(":expires", number((day + 2) * 86_400))
            .expression_attribute_values(
                ":last_start",
                number(DAILY_LOOKUP_LIMIT - LOOKUPS_PER_CALL),
            )
            .send()
            .await;
        match reserved {
            Ok(_) => Ok(true),
            Err(error) => match error.into_service_error() {
                UpdateItemError::ConditionalCheckFailedException(_) => Ok(false),
                other => Err(Failure::new(
                    "lookup_budget",
                    other.meta().code().unwrap_or("unavailable"),
                )),
            },
        }
    }

    async fn search(&self, place: &str) -> Result<Vec<Place>, Failure> {
        let output = self
            .places
            .search_text()
            .query_text(place)
            .set_bias_position(Some(SERVICE_AREA_CENTER.to_vec()))
            .filter(SearchTextFilter::builder().include_countries("USA").build())
            .max_results(3)
            .intended_use(SearchTextIntendedUse::SingleUse)
            .send()
            .await
            .map_err(|error| {
                let code = error
                    .as_service_error()
                    .and_then(|e| e.meta().code())
                    .unwrap_or("unavailable");
                Failure::new("search_text", code)
            })?;
        Ok(output
            .result_items()
            .iter()
            .filter_map(|item| match item.position() {
                &[lon, lat] => Some(Place {
                    name: item.title().to_owned(),
                    address: item.address().and_then(|a| a.label()).map(str::to_owned),
                    position: [lon, lat],
                }),
                _ => None,
            })
            .collect())
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
    async fn validated_options(
        &self,
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
            .query(VALIDATE_SQL, &[&ids(origins), &ids(destinations)])
            .await
            .map_err(|e| fail(e.into()))?;

        let mut only_availability_failed = false;
        let mut ranked = Vec::new();
        for row in &rows {
            let status: String = row.get("status");
            let legs: Value = row.get("facility_legs");
            if matches!(
                status.as_str(),
                "currently_unavailable" | "unknown_availability"
            ) {
                only_availability_failed = true;
            }
            let (Some((entry, origin_miles)), Some((exit, destination_miles))) = (
                find(origins, row.get("origin")),
                find(destinations, row.get("destination")),
            ) else {
                continue;
            };
            let mut facilities: Vec<&str> = legs
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|leg| leg["facility"].as_str())
                .collect();
            facilities.dedup();
            if status != "valid" || facilities.is_empty() {
                continue;
            }
            // shortcut: straight-line access miles, not drive time; upgrade to a Routes matrix if users get cross-river picks.
            let access = origin_miles + destination_miles;
            let option = json!({
                "entry": { "point_id": entry.point_id, "label": entry.label, "direction": entry.direction },
                "exit": { "point_id": exit.point_id, "label": exit.label, "direction": exit.direction },
                "facilities": facilities,
                "access_miles": { "origin": round_tenth(origin_miles), "destination": round_tenth(destination_miles) },
            });
            ranked.push((facilities.len(), access, option));
        }
        ranked.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.total_cmp(&b.1)));
        let options: Vec<Value> = ranked
            .into_iter()
            .take(MAX_OPTIONS)
            .map(|(_, _, option)| option)
            .collect();
        let status = match (options.is_empty(), only_availability_failed) {
            (false, _) => "resolved",
            (true, true) => "currently_unavailable",
            (true, false) => "no_valid_route",
        };
        Ok((status, options))
    }
}

impl Place {
    fn label(&self) -> String {
        self.address.clone().unwrap_or_else(|| self.name.clone())
    }
}

fn find<'a>(side: &[Candidate<'a>], id: &str) -> Option<(&'a Point, f64)> {
    side.iter()
        .find(|c| c.point.point_id == id)
        .map(|c| (c.point, c.miles))
}

/// The nearest interchange per (facility, direction) for this side's role, within reach.
fn candidates_near<'a>(points: &'a [Point], at: [f64; 2], role: &str) -> Vec<Candidate<'a>> {
    let reachable: Vec<Candidate<'a>> = points
        .iter()
        .filter_map(|point| {
            let distance = miles(at, point.location.as_ref()?.coordinates);
            let fits = match point.point_type.as_str() {
                // An airport is a candidate only when the user named that airport.
                "airport" => distance <= AIRPORT_MATCH_MILES,
                kind => kind == role && distance <= MAX_ACCESS_MILES,
            };
            fits.then_some(Candidate {
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
