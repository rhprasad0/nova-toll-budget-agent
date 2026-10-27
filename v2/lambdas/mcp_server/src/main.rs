use std::env;
use std::sync::Arc;

use aws_config::BehaviorVersion;
use aws_sdk_ssm::error::ProvideErrorMetadata;
use mcp_server::{App, BoxError, Salaries, iam_database, log_filter, router};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

#[tokio::main]
async fn main() -> Result<(), BoxError> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::fmt::layer()
                .json()
                .with_span_list(false),
        )
        .with(log_filter())
        .init();

    // For the RDS IAM auth token and the OpenWeb Ninja key in SSM.
    let sdk = aws_config::defaults(BehaviorVersion::latest()).load().await;
    let ssm = aws_sdk_ssm::Client::new(&sdk);
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
        salaries: Salaries::new(
            "https://api.openwebninja.com".into(),
            Arc::new(move || {
                let ssm = ssm.clone();
                Box::pin(async move {
                    let reply = ssm
                        .get_parameter()
                        .name("/nova-toll/openwebninja-api")
                        .with_decryption(true)
                        .send()
                        .await
                        // Only the error code, such as AccessDeniedException, which `LoadKey` logs.
                        .map_err(|error| error.code().unwrap_or("no_response").to_owned())?;
                    let key = reply.parameter.and_then(|parameter| parameter.value);
                    // A value saved from a file keeps its newline, which no header accepts.
                    Ok(key.ok_or("empty_value")?.trim().to_owned())
                })
            }),
            aws_sdk_dynamodb::Client::new(&sdk),
            env::var("LOOKUP_TABLE")?,
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
