use crate::{
    adapters::{continuity, normalize, number},
    selection::{Schedule, Selection, SourceControl},
    spool::{Error, Spool},
};
use chrono::Utc;
use reqwest::Client;
use serde_json::{Value, json};
use std::{env, path::Path, sync::Arc, time::Duration};
use tokio::sync::{RwLock, watch};
use tracing::{info, warn};

pub type Status = Arc<RwLock<Value>>;

pub struct Collector {
    client: Client,
    pub(crate) spool: Spool,
    pub(crate) poly_url: String,
    pub(crate) kalshi_url: String,
    ch_url: String,
    ch_database: String,
    ch_user: String,
    ch_password: String,
    pub(crate) redis_url: String,
    interval: u64,
    schedule: Schedule,
    limit: usize,
    attempted_at: std::collections::BTreeMap<String, i64>,
}

fn setting(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.into())
}

impl Collector {
    pub fn from_env() -> Result<Self, Error> {
        Self::configured("")
    }

    pub fn catalog_from_env() -> Result<Self, Error> {
        Self::configured("catalog")
    }

    pub fn execution_from_env() -> Result<Self, Error> {
        Self::configured("execution")
    }

    fn configured(mode: &str) -> Result<Self, Error> {
        let directory = setting("COLLECTOR_STATE_DIR", "/var/lib/quanthecy");
        let directory = if !mode.is_empty() {
            Path::new(&directory).join(mode)
        } else {
            Path::new(&directory).to_owned()
        };
        let mut spool = Spool::open(&directory)?;
        for (platform, name) in [
            ("polymarket", "POLYMARKET_MARKET_IDS"),
            ("kalshi", "KALSHI_MARKET_TICKERS"),
        ] {
            if mode.is_empty()
                && let Ok(ids) = env::var(name)
                && !ids.trim().is_empty()
            {
                let selected: Vec<String> = ids
                    .split(',')
                    .map(|s| s.trim().to_owned())
                    .filter(|s| !s.is_empty())
                    .collect();
                if selected.len() > 50 {
                    return Err("maximum 50 configured markets per platform".into());
                }
                spool.journal.universe.insert(platform.into(), selected);
            }
        }
        spool.save()?;
        Ok(Self {
            client: Client::builder()
                .user_agent("Quanthecy/0.1 (public market research)")
                .connect_timeout(Duration::from_secs(5))
                .timeout(Duration::from_secs(12))
                .build()?,
            spool,
            poly_url: setting("POLYMARKET_API_URL", "https://gamma-api.polymarket.com"),
            kalshi_url: setting(
                "KALSHI_API_URL",
                "https://external-api.kalshi.com/trade-api/v2",
            ),
            ch_url: setting("CLICKHOUSE_URL", "http://clickhouse:8123"),
            ch_database: setting("CLICKHOUSE_DATABASE", "quanthecy"),
            ch_user: setting("CLICKHOUSE_USER", "quanthecy"),
            ch_password: setting("CLICKHOUSE_PASSWORD", "quanthecy-dev-only"),
            redis_url: setting("REDIS_URL", "redis://redis:6379/0"),
            interval: setting("COLLECTOR_INTERVAL_SECONDS", "60")
                .parse::<u64>()?
                .clamp(15, 3600),
            schedule: Schedule::default(),
            attempted_at: std::collections::BTreeMap::new(),
            limit: setting("COLLECTOR_MARKETS_PER_PLATFORM", "10")
                .parse::<usize>()?
                .clamp(1, 50),
        })
    }

    pub(crate) fn control(&self, platform: &str) -> SourceControl {
        self.spool
            .journal
            .selection
            .as_ref()
            .and_then(|selection| selection.sources.as_ref())
            .and_then(|sources| sources.get(platform))
            .cloned()
            .unwrap_or(SourceControl {
                enabled: true,
                interval_seconds: self.interval,
            })
    }

    pub(crate) async fn get(&self, url: &str) -> Result<Value, Error> {
        for attempt in 0..3 {
            match self.client.get(url).send().await {
                Ok(response) if response.status().is_success() => {
                    return Ok(response.json().await?);
                }
                Ok(response)
                    if attempt < 2
                        && (response.status().is_server_error()
                            || response.status().as_u16() == 429) =>
                {
                    let delay = response
                        .headers()
                        .get("retry-after")
                        .and_then(|h| h.to_str().ok())
                        .and_then(|s| s.parse::<u64>().ok())
                        .unwrap_or(1 << attempt)
                        .clamp(1, 15);
                    tokio::time::sleep(Duration::from_secs(delay)).await;
                }
                Ok(response) => {
                    return Err(format!("exchange HTTP {}", response.status().as_u16()).into());
                }
                Err(_) if attempt < 2 => {
                    tokio::time::sleep(Duration::from_secs(1 << attempt)).await
                }
                Err(_) => return Err("exchange network request failed".into()),
            }
        }
        Err("exchange retries exhausted".into())
    }

    async fn discover(&mut self, platform: &str) -> Result<(), Error> {
        if self
            .spool
            .journal
            .universe
            .get(platform)
            .is_some_and(|v| !v.is_empty())
        {
            return Ok(());
        }
        let mut candidates = Vec::new();
        let mut cursor = String::new();
        for page in 0..2 {
            let url = if platform == "polymarket" {
                format!(
                    "{}/markets?limit=100&offset={}&active=true&closed=false",
                    self.poly_url,
                    page * 100
                )
            } else {
                format!(
                    "{}/markets?limit=100&status=open&mve_filter=exclude&cursor={}",
                    self.kalshi_url, cursor
                )
            };
            let data = self.get(&url).await?;
            let rows = if platform == "polymarket" {
                data.as_array()
            } else {
                data["markets"].as_array()
            }
            .ok_or("invalid discovery response")?;
            for raw in rows {
                if let Ok(observation) = normalize(platform, raw, Utc::now(), &url)
                    && observation["market"]["status"] == "OPEN"
                {
                    candidates.push((
                        number(&observation["volume"]["value"]).unwrap_or(0.0),
                        observation["market"]["exchange_id"]
                            .as_str()
                            .ok_or("market id")?
                            .to_owned(),
                    ));
                }
            }
            cursor = data["cursor"].as_str().unwrap_or("").to_owned();
            if rows.len() < 100 || (platform == "kalshi" && cursor.is_empty()) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        candidates.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
        let mut ids: Vec<String> = Vec::new();
        for (_, id) in candidates {
            if !ids.contains(&id) && ids.len() < self.limit {
                ids.push(id);
            }
        }
        if ids.is_empty() {
            return Err("no supported binary markets discovered".into());
        }
        info!(%platform, markets = ids.len(), "discovery complete (bounded sample)");
        self.spool.journal.universe.insert(platform.into(), ids);
        self.spool.save()
    }

    pub(crate) async fn ch(&self, query: &str, data: String) -> Result<(), Error> {
        let response = self
            .client
            .post(&self.ch_url)
            .query(&[
                ("database", self.ch_database.as_str()),
                ("query", query),
                ("date_time_input_format", "best_effort"),
            ])
            .header("X-ClickHouse-User", &self.ch_user)
            .header("X-ClickHouse-Key", &self.ch_password)
            .body(data)
            .send()
            .await?;
        if !response.status().is_success() {
            return Err(format!("ClickHouse HTTP {}", response.status().as_u16()).into());
        }
        // wait_end_of_query is unnecessary for INSERT; successful synchronous writes precede the commit row.
        Ok(())
    }

    async fn deliver(&mut self) -> Result<(), Error> {
        if self.spool.journal.pending.is_empty() {
            return Ok(());
        }
        let journal = &self.spool.journal;
        let mut lines = String::new();
        for (observation, raw) in journal.pending.iter().zip(&journal.raw) {
            let row = json!({"collector_id":journal.collector_id,"batch_id":journal.batch_id,
                "observation_id":observation["observation_id"],"platform":observation["platform"],
                "market_id":observation["market"]["id"],"outcome_id":observation["outcome"]["id"],
                "received_at":observation["received_at"],"probability":observation["probability"]["value"],
                "best_bid":observation["best_bid"],"best_ask":observation["best_ask"],
                "volume":observation["volume"]["value"],"volume_unit":observation["volume"]["unit"].as_str().unwrap_or(""),
                "quality_flags":observation["quality_flags"],"envelope":observation.to_string(),"raw_payload":raw.to_string()});
            lines.push_str(&row.to_string());
            lines.push('\n');
        }
        self.ch("INSERT INTO market_observations FORMAT JSONEachRow", lines)
            .await?;
        self.ch("INSERT INTO ingestion_batches FORMAT JSONEachRow", json!({"collector_id":journal.collector_id,
            "batch_id":journal.batch_id,"row_count":journal.pending.len(),"committed_at":crate::adapters::timestamp(Utc::now())}).to_string()).await?;
        // Redis is a disposable view: a failure never blocks durable progress.
        if let Err(error) = self.cache(&journal.pending).await {
            warn!(error_type = %error, "live cache unavailable");
        }
        info!(
            batch_id = journal.batch_id,
            rows = journal.pending.len(),
            "batch persisted"
        );
        self.spool.acknowledge()
    }

    async fn cache(&self, observations: &[Value]) -> Result<(), Error> {
        let client = redis::Client::open(self.redis_url.as_str())?;
        let mut connection = tokio::time::timeout(
            Duration::from_secs(3),
            client.get_multiplexed_async_connection(),
        )
        .await??;
        // Compare collection time, so delayed/replayed batches cannot replace newer state.
        let script = redis::Script::new(
            "local old = redis.call('GET', KEYS[1]); if not old or cjson.decode(old).received_at <= ARGV[1] then redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]); return 1 end; return 0",
        );
        for value in observations {
            let key = format!(
                "market:{}:{}",
                value["platform"].as_str().ok_or("platform")?,
                value["market"]["id"].as_str().ok_or("market")?
            );
            let _: i32 = tokio::time::timeout(
                Duration::from_secs(3),
                script
                    .key(key)
                    .arg(value["received_at"].as_str().ok_or("time")?)
                    .arg(value.to_string())
                    .arg(
                        self.control(value["platform"].as_str().ok_or("platform")?)
                            .interval_seconds
                            * 3,
                    )
                    .invoke_async(&mut connection),
            )
            .await??;
        }
        Ok(())
    }

    // Only allowlisted error categories enter public telemetry; never URLs or credentials.
    async fn source_status(&self, platform: &str, error: Option<&str>) {
        let error_code = error.map(|message| {
            if message.contains("network") {
                "network"
            } else if message.contains("429") {
                "rate_limited"
            } else if message.starts_with("exchange HTTP") {
                "exchange"
            } else {
                "invalid_data"
            }
        });
        let record =
            json!({"checked_at": crate::adapters::timestamp(Utc::now()), "error_code": error_code});
        let result = tokio::time::timeout(Duration::from_millis(500), async {
            let client = redis::Client::open(self.redis_url.as_str())?;
            let mut connection = client.get_multiplexed_async_connection().await?;
            redis::cmd("SET")
                .arg(format!("collector:status:{platform}"))
                .arg(record.to_string())
                .arg("EX")
                .arg(300)
                .query_async::<()>(&mut connection)
                .await
        })
        .await;
        if !matches!(result, Ok(Ok(()))) {
            warn!(%platform, "collection telemetry unavailable");
        }
    }

    async fn refresh_selection(&mut self) {
        self.refresh_configuration(true).await;
    }

    pub(crate) async fn refresh_configuration(&mut self, acknowledge: bool) {
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            let client = redis::Client::open(self.redis_url.as_str())?;
            let mut connection = client.get_multiplexed_async_connection().await?;
            // GETRANGE bounds the read before decoding even if a broken publisher writes a huge value.
            let raw: Vec<u8> = redis::cmd("GETRANGE")
                .arg("collector:selection:v1")
                .arg(0)
                .arg(524288)
                .query_async(&mut connection)
                .await?;
            if !raw.is_empty() {
                match Selection::parse(&raw)
                    .and_then(|selection| self.spool.apply_selection(selection))
                {
                    Ok(()) => {}
                    Err(_) => warn!("operator selection rejected; retaining last good selection"),
                }
            }
            if acknowledge && let Some(selection) = &self.spool.journal.selection {
                let ack = json!({"revision":selection.revision,"enabled":selection.enabled,
                    "collector_id":self.spool.journal.collector_id, "schema_version":selection.schema_version,
                    "checked_at":crate::adapters::timestamp(Utc::now())});
                redis::cmd("SET")
                    .arg("collector:selection-status:v1")
                    .arg(ack.to_string())
                    .arg("EX")
                    .arg(300)
                    .query_async::<()>(&mut connection)
                    .await?;
            }
            Ok::<(), Error>(())
        })
        .await;
        if !matches!(result, Ok(Ok(()))) {
            warn!("operator selection unavailable; retaining last good selection");
        }
    }

    pub(crate) fn market_interval(&self, platform: &str, id: &str) -> u64 {
        let base = self.control(platform).interval_seconds;
        let configured = self
            .spool
            .journal
            .selection
            .as_ref()
            .filter(|s| s.enabled)
            .and_then(|s| s.intervals.as_ref())
            .and_then(|map| map.get(platform))
            .and_then(|map| map.get(id))
            .copied()
            .unwrap_or(base)
            .max(base);
        match self
            .spool
            .journal
            .latest
            .get(&crate::adapters::stable_id(platform, "market", id))
            .and_then(|row| row["market"]["status"].as_str())
        {
            Some("RESOLVED") => configured.max(86400),
            Some("CLOSED") => configured.max(3600),
            _ => configured,
        }
    }

    async fn cycle(&mut self, status: &Status) -> Result<(), Error> {
        self.refresh_selection().await;
        self.deliver().await?;
        let managed = self
            .spool
            .journal
            .selection
            .as_ref()
            .filter(|selection| selection.enabled)
            .cloned();
        let mut observations = Vec::new();
        let mut payloads = Vec::new();
        let mut failures = 0;
        for platform in ["polymarket", "kalshi"] {
            self.refresh_selection().await;
            let control = self.control(platform);
            if !control.enabled {
                continue;
            }
            let managed = self
                .spool
                .journal
                .selection
                .as_ref()
                .filter(|s| s.enabled)
                .cloned();
            if managed.is_none()
                && let Err(error) = self.discover(platform).await
            {
                failures += 1;
                warn!(%platform, error_type = %error, "discovery failed");
                self.source_status(platform, Some(&error.to_string())).await;
                continue;
            }
            let mut ids = managed.as_ref().map_or_else(
                || self.spool.journal.universe[platform].clone(),
                |selection| selection.universe[platform].clone(),
            );
            // Oldest observations first; bounded batches prevent standard-tier backlogs
            // from starving another exchange or exceeding reconciliation read bounds.
            ids.sort_by_key(|id| {
                let key = crate::adapters::stable_id(platform, "market", id);
                let observed = self
                    .spool
                    .journal
                    .latest
                    .get(&key)
                    .and_then(|row| row["received_at"].as_str())
                    .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
                    .map_or(0, |at| at.timestamp());
                observed.max(*self.attempted_at.get(&key).unwrap_or(&0))
            });
            let mut source_error = None;
            let mut attempted = 0;
            for id in ids {
                self.refresh_selection().await;
                if !self.control(platform).enabled {
                    break;
                }
                if let Some(current) = &self.spool.journal.selection
                    && current.enabled
                    && !current.universe[platform].contains(&id)
                {
                    continue;
                }
                let key = crate::adapters::stable_id(platform, "market", &id);
                let interval = self.market_interval(platform, &id);
                let last = self
                    .spool
                    .journal
                    .latest
                    .get(&key)
                    .and_then(|row| row["received_at"].as_str())
                    .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok());
                if last.is_some_and(|at| {
                    (Utc::now() - at.with_timezone(&Utc)).num_seconds() < interval as i64
                }) {
                    continue;
                }
                let pacing = SourceControl {
                    enabled: true,
                    interval_seconds: interval,
                };
                if !self
                    .schedule
                    .claim(&key, &pacing, std::time::Instant::now())
                {
                    continue;
                }
                attempted += 1;
                self.attempted_at.insert(key, Utc::now().timestamp());
                let base = if platform == "polymarket" {
                    &self.poly_url
                } else {
                    &self.kalshi_url
                };
                let mut url = reqwest::Url::parse(&format!("{base}/markets/"))?;
                if platform == "polymarket" {
                    url.set_path(&format!(
                        "{}/markets",
                        url.path().trim_end_matches("/markets/")
                    ));
                    url.query_pairs_mut()
                        .append_pair("id", &id)
                        .append_pair("limit", "1");
                } else {
                    url.path_segments_mut()
                        .map_err(|_| "invalid exchange base URL")?
                        .pop_if_empty()
                        .push(&id);
                }
                let result = self.get(url.as_str()).await.and_then(|data| {
                    let raw = if platform == "kalshi" {
                        data["market"].clone()
                    } else {
                        data.as_array()
                            .and_then(|rows| rows.iter().find(|row| row["id"] == id))
                            .cloned()
                            .ok_or("selected Polymarket market absent")?
                    };
                    let value = normalize(platform, &raw, Utc::now(), url.as_str())?;
                    if value["market"]["exchange_id"] != id {
                        return Err("selected market identity mismatch".into());
                    }
                    Ok((value, raw))
                });
                match result {
                    Ok((mut observation, raw)) => {
                        if let Some(old) = self
                            .spool
                            .journal
                            .latest
                            .get(observation["market"]["id"].as_str().ok_or("market")?)
                        {
                            continuity(old, &mut observation, interval as i64);
                        }
                        observations.push(observation);
                        payloads.push(raw);
                    }
                    Err(error) => {
                        failures += 1;
                        warn!(%platform, market_id = %id, error_type = %error, "snapshot failed");
                        source_error = Some(error.to_string());
                    }
                }
                tokio::time::sleep(Duration::from_millis(250)).await;
                if attempted >= 50 {
                    break;
                }
            }
            if attempted > 0 {
                self.source_status(platform, source_error.as_deref()).await;
            }
        }
        if !observations.is_empty() {
            let staged_at = crate::adapters::timestamp(Utc::now());
            for observation in &mut observations {
                observation["recorded_at"] = json!(staged_at);
            }
            self.spool.stage(observations, payloads)?;
            self.deliver().await?;
        }
        let snapshot = json!({"status":if failures == 0 {"ready"} else {"degraded"},"mode":"rest_snapshots",
            "sources":{"polymarket":self.control("polymarket"),"kalshi":self.control("kalshi")},"universe":managed.as_ref().map_or(&self.spool.journal.universe, |selection| &selection.universe),
            "selection_revision":self.spool.journal.selection.as_ref().map(|selection| selection.revision),
            "collector_id":self.spool.journal.collector_id,"last_batch_id":self.spool.journal.batch_id,
            "last_cycle_at":crate::adapters::timestamp(Utc::now()),"failures":failures});
        *status.write().await = snapshot;
        Ok(())
    }

    pub async fn run(mut self, status: Status, mut stop: watch::Receiver<bool>) {
        loop {
            let started = tokio::time::Instant::now();
            tokio::select! {
                _ = stop.changed() => break,
                result = self.cycle(&status) => if let Err(error) = result {
                    *status.write().await = json!({"status":"degraded","mode":"rest_snapshots","pending_rows":self.spool.journal.pending.len()});
                    warn!(error_type = %error, "cycle failed; durable pending batch will be replayed");
                }
            }
            tokio::select! {
                _ = stop.changed() => break,
                _ = tokio::time::sleep_until(started + Duration::from_secs(5)) => {}
            }
        }
        info!("collector stopped; journal retained");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        Json, Router,
        routing::{get, post},
    };
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[tokio::test]
    async fn paused_sources_skip_http_and_resume_fetches_only_enabled_source() {
        let calls = Arc::new(AtomicUsize::new(0));
        let counter = calls.clone();
        let app = Router::new()
            .route(
                "/markets",
                get(move || {
                    counter.fetch_add(1, Ordering::SeqCst);
                    async {
                        Json(vec![
                            serde_json::from_str::<Value>(include_str!(
                                "../../../tests/fixtures/polymarket/market-rest.json"
                            ))
                            .unwrap(),
                        ])
                    }
                }),
            )
            .route("/", post(|| async { "" }));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let directory =
            std::env::temp_dir().join(format!("quanthecy-runtime-{}", uuid::Uuid::new_v4()));
        let mut collector = Collector {
            client: Client::new(),
            spool: Spool::open(&directory).unwrap(),
            poly_url: base.clone(),
            kalshi_url: base.clone(),
            ch_url: base,
            ch_database: "fixture".into(),
            ch_user: "fixture".into(),
            ch_password: "fixture".into(),
            redis_url: "redis://127.0.0.1:1".into(),
            interval: 60,
            limit: 10,
            schedule: Schedule::default(),
            attempted_at: std::collections::BTreeMap::new(),
        };
        let mut plan = json!({"schema_version":2,"revision":1,"enabled":true,
            "universe":{"polymarket":["559651"],"kalshi":["NO-REQUEST"]},
            "sources":{"polymarket":{"enabled":false,"interval_seconds":60},"kalshi":{"enabled":false,"interval_seconds":60}}});
        collector
            .spool
            .apply_selection(Selection::parse(plan.to_string().as_bytes()).unwrap())
            .unwrap();
        let state = Arc::new(RwLock::new(json!({})));
        collector.cycle(&state).await.unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        plan["revision"] = json!(2);
        plan["sources"]["polymarket"]["enabled"] = json!(true);
        collector
            .spool
            .apply_selection(Selection::parse(plan.to_string().as_bytes()).unwrap())
            .unwrap();
        collector.cycle(&state).await.unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(collector.spool.journal.batch_id, 1);
        collector.cycle(&state).await.unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1); // Frequency enforced.
        assert_eq!(state.read().await["failures"], 0); // Disabled Kalshi never requested.
        // Lifecycle throttling uses persisted status, never a missing directory entry.
        let key = crate::adapters::stable_id("polymarket", "market", "559651");
        assert_eq!(collector.market_interval("polymarket", "559651"), 60);
        collector.spool.journal.latest.get_mut(&key).unwrap()["market"]["status"] = json!("CLOSED");
        assert_eq!(collector.market_interval("polymarket", "559651"), 3600);
        collector.spool.journal.latest.get_mut(&key).unwrap()["market"]["status"] =
            json!("RESOLVED");
        assert_eq!(collector.market_interval("polymarket", "559651"), 86400);
        collector.spool.journal.latest.get_mut(&key).unwrap()["market"]["status"] = json!("OPEN");
        assert_eq!(collector.market_interval("polymarket", "559651"), 60);
        drop(collector);
        server.abort();
        std::fs::remove_dir_all(directory).unwrap();
    }
}
