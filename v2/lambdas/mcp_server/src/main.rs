use std::env;

use aws_config::BehaviorVersion;
use mcp_server::{App, BoxError, iam_database, log_filter, router};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

#[tokio::main]
async fn main() -> Result<(), BoxError> {
    tracing_subscriber::registry()
        .with(tracing_subscriber::fmt::layer().json())
        .with(log_filter())
        .init();

    // Only for the RDS IAM auth token: the server calls no AWS service APIs.
    let sdk = aws_config::defaults(BehaviorVersion::latest()).load().await;
    let app = App {
        database: iam_database(
            &sdk,
            env::var("DB_HOST")?,
            env::var("DB_PORT")?.parse()?,
            env::var("DB_NAME")?,
            &env::var("DB_CA_BUNDLE_PATH")?,
            env::var("DB_USER")?,
            env::var("PRICING_DB_USER")?,
        )?,
    };

    if env::var_os("AWS_LAMBDA_RUNTIME_API").is_some() {
        return lambda_http::run(router(app, &["mcp.tollchat.ai"])).await;
    }
    // Local run for Muse Code and manual checks, against the same IAM/TLS database path.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:8080").await?;
    axum::serve(listener, router(app, &["localhost", "127.0.0.1"])).await?;
    Ok(())
}
