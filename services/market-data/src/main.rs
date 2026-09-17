use axum::{Json, Router, extract::State, http::StatusCode, routing::get};
use quanthecy_market_data::collector::{Collector, Status};
use serde_json::{Value, json};
use std::{
    env,
    error::Error,
    io::{Read, Write},
    net::TcpStream,
    sync::Arc,
    time::Duration,
};
use tokio::signal;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    if env::args().nth(1).as_deref() == Some("healthcheck") {
        return healthcheck();
    }
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();
    let collector = Collector::from_env().map_err(|e| e.to_string())?;
    let state: Status = Arc::new(tokio::sync::RwLock::new(json!({"status":"starting"})));
    let (stop, receiver) = tokio::sync::watch::channel(false);
    let catalog = Collector::catalog_from_env().map_err(|e| e.to_string())?;
    let catalog_task = tokio::spawn(quanthecy_market_data::catalog::run(
        catalog,
        receiver.clone(),
    ));
    let task = tokio::spawn(collector.run(state.clone(), receiver));
    let app = Router::new()
        .route("/health", get(|| async { Json(json!({"status": "ok"})) }))
        .route("/ready", get(ready))
        .route("/status", get(status))
        .with_state(state);
    let bind = env::var("COLLECTOR_BIND").unwrap_or_else(|_| "0.0.0.0:8080".into());
    let listener = tokio::net::TcpListener::bind(&bind).await?;
    info!(service = "market-data", mode = "rest_snapshots", collection_enabled = true, %bind, "starting");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown())
        .await?;
    let _ = stop.send(true);
    task.await?;
    catalog_task.await?;
    info!(service = "market-data", "shutdown complete");
    Ok(())
}

async fn status(State(state): State<Status>) -> Json<Value> {
    Json(state.read().await.clone())
}

async fn ready(State(state): State<Status>) -> (StatusCode, Json<Value>) {
    let value = state.read().await.clone();
    let code = if value["status"] == "ready" {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (code, Json(value))
}

async fn shutdown() {
    #[cfg(unix)]
    {
        let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("SIGTERM handler can be installed");
        tokio::select! {
            _ = signal::ctrl_c() => {},
            _ = term.recv() => {},
        }
    }
    #[cfg(not(unix))]
    signal::ctrl_c()
        .await
        .expect("Ctrl-C handler can be installed");
}

fn healthcheck() -> Result<(), Box<dyn Error>> {
    let mut connection =
        TcpStream::connect_timeout(&"127.0.0.1:8080".parse()?, Duration::from_secs(3))?;
    connection.set_read_timeout(Some(Duration::from_secs(3)))?;
    connection.set_write_timeout(Some(Duration::from_secs(3)))?;
    connection
        .write_all(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")?;
    let mut response = [0_u8; 12];
    connection.read_exact(&mut response)?;
    if &response != b"HTTP/1.1 200" {
        return Err("collector health check failed".into());
    }
    Ok(())
}
