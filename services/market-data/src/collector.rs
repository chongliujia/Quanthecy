use crate::{
    adapters::{continuity, normalize, number},
    selection::Selection,
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
    spool: Spool,
    poly_url: String,
    kalshi_url: String,
    ch_url: String,
    ch_database: String,
    ch_user: String,
    ch_password: String,
    redis_url: String,
    interval: u64,
    limit: usize,
}

fn setting(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.into())
}

impl Collector {
    pub fn from_env() -> Result<Self, Error> {
        let mut spool = Spool::open(Path::new(&setting(
            "COLLECTOR_STATE_DIR",
            "/var/lib/quanthecy",
        )))?;
        for (platform, name) in [
            ("polymarket", "POLYMARKET_MARKET_IDS"),
            ("kalshi", "KALSHI_MARKET_TICKERS"),
        ] {
            if let Ok(ids) = env::var(name)
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
            limit: setting("COLLECTOR_MARKETS_PER_PLATFORM", "10")
                .parse::<usize>()?
                .clamp(1, 50),
        })
    }

    async fn get(&self, url: &str) -> Result<Value, Error> {
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

    async fn ch(&self, query: &str, data: String) -> Result<(), Error> {
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
                    .arg(self.interval * 3)
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
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            let client = redis::Client::open(self.redis_url.as_str())?;
            let mut connection = client.get_multiplexed_async_connection().await?;
            // GETRANGE bounds the read before decoding even if a broken publisher writes a huge value.
            let raw: Vec<u8> = redis::cmd("GETRANGE")
                .arg("collector:selection:v1")
                .arg(0)
                .arg(65536)
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
            if let Some(selection) = &self.spool.journal.selection {
                let ack = json!({"revision":selection.revision,"enabled":selection.enabled,
                    "collector_id":self.spool.journal.collector_id,
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

    async fn cycle(&mut self, status: &Status) -> Result<(), Error> {
        self.deliver().await?;
        self.refresh_selection().await;
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
            if managed.is_none()
                && let Err(error) = self.discover(platform).await
            {
                failures += 1;
                warn!(%platform, error_type = %error, "discovery failed");
                self.source_status(platform, Some(&error.to_string())).await;
                continue;
            }
            let ids = managed.as_ref().map_or_else(
                || self.spool.journal.universe[platform].clone(),
                |selection| selection.universe[platform].clone(),
            );
            let mut source_error = None;
            for id in ids {
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
                    normalize(platform, &raw, Utc::now(), url.as_str())
                        .map(|value| (value, raw))
                        .map_err(Into::into)
                });
                match result {
                    Ok((mut observation, raw)) => {
                        if let Some(old) = self
                            .spool
                            .journal
                            .latest
                            .get(observation["market"]["id"].as_str().ok_or("market")?)
                        {
                            continuity(old, &mut observation, self.interval as i64);
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
            }
            self.source_status(platform, source_error.as_deref()).await;
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
            "collection_enabled":true,"interval_seconds":self.interval,"universe":managed.as_ref().map_or(&self.spool.journal.universe, |selection| &selection.universe),
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
                _ = tokio::time::sleep_until(started + Duration::from_secs(self.interval)) => {}
            }
        }
        info!("collector stopped; journal retained");
    }
}
