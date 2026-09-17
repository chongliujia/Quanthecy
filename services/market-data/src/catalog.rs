//! Low-frequency discovery runs independently of quote polling. Each page is one
//! durable ClickHouse record, replayed from disk before any cursor can advance.
use crate::{
    adapters::{normalize, number, timestamp},
    collector::Collector,
    selection::DiscoveryControl,
    spool::Error,
};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::BTreeSet, time::Duration};
use tokio::sync::watch;
use uuid::Uuid;

#[derive(Clone, Default, Serialize, Deserialize)]
pub struct ScanState {
    pub scan_id: Uuid,
    pub cursor: String,
    pub pages: u32,
    pub rows_seen: u32,
    pub accepted: u32,
    pub skipped: u32,
    pub next_at: i64,
    pub finished: bool,
    #[serde(default)]
    pub failed: bool,
}

pub fn page_url(base: &str, platform: &str, cursor: &str) -> Result<reqwest::Url, Error> {
    let path = if platform == "polymarket" {
        "markets/keyset"
    } else {
        "markets"
    };
    let mut url = reqwest::Url::parse(&format!("{base}/{path}"))?;
    url.query_pairs_mut().append_pair("limit", "100");
    if platform == "polymarket" {
        url.query_pairs_mut()
            .append_pair("closed", "false")
            .append_pair("after_cursor", cursor);
    } else {
        url.query_pairs_mut()
            .append_pair("status", "open")
            .append_pair("mve_filter", "exclude")
            .append_pair("cursor", cursor);
    }
    Ok(url)
}

pub fn parse_page(
    platform: &str,
    data: &Value,
    old: &ScanState,
    policy: &DiscoveryControl,
    page_id: u64,
    source: &str,
) -> Result<(ScanState, Value), Error> {
    if platform == "kalshi" && !data["cursor"].is_string() {
        return Err("missing directory cursor".into());
    }
    let rows = data["markets"]
        .as_array()
        .ok_or("invalid directory response")?;
    if rows.len() > 100 {
        return Err("directory page exceeds requested bound".into());
    }
    let cursor_value = &data[if platform == "polymarket" {
        "next_cursor"
    } else {
        "cursor"
    }];
    if !cursor_value.is_null() && !cursor_value.is_string() {
        return Err("invalid directory cursor".into());
    }
    let cursor = cursor_value.as_str().unwrap_or("");
    if cursor.len() > 4096 || (!cursor.is_empty() && (cursor == old.cursor || rows.is_empty())) {
        return Err("directory cursor did not advance".into());
    }
    let now = Utc::now();
    let mut seen = BTreeSet::new();
    let mut items = Vec::new();
    let mut rejected = std::collections::BTreeMap::<&str, u32>::new();
    // Pagination cursors can make URLs exceed the observation provenance bound.
    // Metadata normalization needs the endpoint identity, not the transient cursor.
    let metadata_source = source.split('?').next().unwrap_or(source);
    for raw in rows {
        match normalize(platform, raw, now, metadata_source) {
            Ok(row) => {
                let market = &row["market"];
                let exchange_id = market["exchange_id"].as_str().ok_or("directory id")?;
                let valid_id = if platform == "polymarket" {
                    exchange_id.bytes().all(|b| b.is_ascii_digit())
                } else {
                    exchange_id.bytes().all(|b| {
                        b.is_ascii_uppercase() || b.is_ascii_digit() || b"._-".contains(&b)
                    })
                };
                if !valid_id || !seen.insert(exchange_id.to_owned()) {
                    continue;
                }
                items.push(json!({"id":market["id"],"exchange_id":exchange_id,"title":market["title"],
                "status":market["status"],"closes_at":market["closes_at"],
                "volume_24h":number(&raw[if platform == "polymarket" { "volume24hr" } else { "volume_24h_fp" }]),
                "volume_unit":if platform == "polymarket" { "USD" } else { "CONTRACTS" }}));
            }
            Err(error) => {
                let category = if error.contains("only") && error.contains("supported") {
                    "unsupported_contract"
                } else if error.contains("missing event") {
                    "missing_event"
                } else if error.contains("missing YES token") {
                    "missing_outcome"
                } else {
                    "invalid_metadata"
                };
                *rejected.entry(category).or_default() += 1;
            }
        }
    }
    if !rejected.is_empty() {
        tracing::info!(%platform, rejected = ?rejected, "directory records excluded");
    }
    let mut state = old.clone();
    state.failed = false;
    state.pages += 1;
    state.rows_seen += rows.len() as u32;
    state.accepted += items.len() as u32;
    state.skipped += (rows.len() - items.len()) as u32;
    let complete = cursor.is_empty(); // Short cursor pages are not necessarily the last page.
    state.finished = complete || state.pages >= policy.max_pages;
    state.cursor = cursor.to_owned();
    state.next_at = now.timestamp()
        + if state.finished {
            policy.interval_seconds
        } else {
            policy.page_interval_seconds
        } as i64;
    let envelope = json!({"schema_version":1,"page_id":page_id,"platform":platform,"observed_at":timestamp(now),
        "scan_id":state.scan_id,"pages":state.pages,"rows_seen":state.rows_seen,"accepted":state.accepted,
        "skipped":state.skipped,"state":if complete { "complete" } else if state.finished { "capped" } else { "scanning" },"items":items});
    Ok((state, envelope))
}

async fn deliver(collector: &mut Collector) -> Result<(), Error> {
    if let Some(page) = &collector.spool.journal.catalog_pending {
        collector
            .ch(
                "INSERT INTO market_catalog_pages FORMAT JSONEachRow",
                json!({
                    "collector_id":collector.spool.journal.collector_id,"page_id":page["page_id"],
                    "received_at":page["observed_at"],"envelope":page.to_string()
                })
                .to_string(),
            )
            .await?;
        collector.spool.journal.catalog_pending = None;
        collector.spool.save()?;
    }
    Ok(())
}

async fn tick(collector: &mut Collector, platform: &str) -> Result<(), Error> {
    collector.refresh_configuration(false).await;
    deliver(collector).await?;
    let Some(policy) = collector
        .spool
        .journal
        .selection
        .as_ref()
        .and_then(|s| s.discovery.clone())
    else {
        return Ok(());
    };
    if !policy.enabled || !collector.control(platform).enabled {
        return Ok(());
    }
    let old = collector
        .spool
        .journal
        .catalog
        .entry(platform.into())
        .or_default();
    if old.next_at > Utc::now().timestamp() {
        return Ok(());
    }
    if old.finished || old.scan_id.is_nil() {
        *old = ScanState {
            scan_id: Uuid::new_v4(),
            ..ScanState::default()
        };
    }
    let old = old.clone();
    let base = if platform == "polymarket" {
        &collector.poly_url
    } else {
        &collector.kalshi_url
    };
    let url = page_url(base, platform, &old.cursor)?;
    let data = collector.get(url.as_str()).await?;
    let page_id = collector.spool.journal.catalog_page_id + 1;
    let (next, page) = parse_page(platform, &data, &old, &policy, page_id, url.as_str())?;
    collector
        .spool
        .journal
        .catalog
        .insert(platform.into(), next);
    collector.spool.journal.catalog_page_id = page_id;
    collector.spool.journal.catalog_pending = Some(page);
    collector.spool.save()?;
    deliver(collector).await
}

async fn telemetry(collector: &Collector, platform: &str, error: bool) {
    let record = json!({"checked_at":timestamp(Utc::now()),"error":error || collector.spool.journal.catalog.get(platform).is_some_and(|s| s.failed),
        "revision":collector.spool.journal.selection.as_ref().map(|s| s.revision),
        "next_at":collector.spool.journal.catalog.get(platform).map(|s| s.next_at)});
    let _ = tokio::time::timeout(Duration::from_millis(500), async {
        let client = redis::Client::open(collector.redis_url.as_str())?;
        let mut connection = client.get_multiplexed_async_connection().await?;
        redis::cmd("SET")
            .arg(format!("collector:catalog:{platform}"))
            .arg(record.to_string())
            .arg("EX")
            .arg(180)
            .query_async::<()>(&mut connection)
            .await
    })
    .await;
}

pub async fn run(mut collector: Collector, mut stop: watch::Receiver<bool>) {
    loop {
        for platform in ["polymarket", "kalshi"] {
            let result = tokio::select! {
                _ = stop.changed() => return,
                result = tick(&mut collector, platform) => result,
            };
            if result.is_err() {
                // Failed pages retain their cursor and use a bounded retry backoff.
                collector
                    .spool
                    .journal
                    .catalog
                    .entry(platform.into())
                    .or_default()
                    .next_at = Utc::now().timestamp() + 60;
                collector
                    .spool
                    .journal
                    .catalog
                    .entry(platform.into())
                    .or_default()
                    .failed = true;
                let _ = collector.spool.save();
                tracing::warn!(%platform, "directory page failed; retaining cursor and pending page");
            }
            telemetry(&collector, platform, result.is_err()).await;
        }
        tokio::select! { _ = stop.changed() => return, _ = tokio::time::sleep(Duration::from_secs(5)) => {} }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn policy() -> DiscoveryControl {
        DiscoveryControl {
            enabled: true,
            interval_seconds: 3600,
            page_interval_seconds: 10,
            max_pages: 2,
        }
    }
    #[test]
    fn staged_page_and_cursor_survive_restart_together() {
        use crate::spool::Spool;
        let directory = std::env::temp_dir().join(format!("catalog-recovery-{}", Uuid::new_v4()));
        {
            let mut spool = Spool::open(&directory).unwrap();
            spool.journal.catalog_page_id = 1;
            spool.journal.catalog_pending = Some(json!({"page_id":1,"items":[]}));
            let state = ScanState {
                cursor: "next".into(),
                pages: 1,
                ..ScanState::default()
            };
            spool.journal.catalog.insert("kalshi".into(), state);
            spool.save().unwrap();
        }
        {
            let spool = Spool::open(&directory).unwrap();
            assert_eq!(
                spool.journal.catalog_pending.as_ref().unwrap()["page_id"],
                1
            );
            assert_eq!(spool.journal.catalog["kalshi"].cursor, "next");
            assert_eq!(spool.journal.catalog_page_id, 1);
        }
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn long_pagination_cursor_does_not_exclude_valid_metadata() {
        let raw: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/polymarket/market-rest.json"
        ))
        .unwrap();
        let cursor = "x".repeat(300);
        let url = page_url("https://gamma-api.polymarket.com", "polymarket", &cursor).unwrap();
        assert!(url.as_str().len() > 255);
        let (_, page) = parse_page(
            "polymarket",
            &json!({"markets":[raw],"next_cursor":"next"}),
            &ScanState {
                cursor,
                ..ScanState::default()
            },
            &policy(),
            1,
            url.as_str(),
        )
        .unwrap();
        assert_eq!(page["accepted"], 1);
        assert_eq!(page["skipped"], 0);
    }

    #[test]
    fn cursor_short_page_continues_and_cap_is_not_complete() {
        let raw: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/kalshi/market-rest.json"
        ))
        .unwrap();
        let old = ScanState {
            scan_id: Uuid::new_v4(),
            ..ScanState::default()
        };
        let (next, page) = parse_page(
            "kalshi",
            &json!({"markets":[raw.clone()],"cursor":"abc+/="}),
            &old,
            &policy(),
            1,
            "fixture",
        )
        .unwrap();
        assert_eq!(page["state"], "scanning");
        assert!(!next.finished);
        let (_, page) = parse_page(
            "kalshi",
            &json!({"markets":[raw],"cursor":"next"}),
            &next,
            &policy(),
            2,
            "fixture",
        )
        .unwrap();
        assert_eq!(page["state"], "capped");
        let (_, page) = parse_page(
            "kalshi",
            &json!({"markets":[],"cursor":""}),
            &next,
            &policy(),
            2,
            "fixture",
        )
        .unwrap();
        assert_eq!(page["state"], "complete");
        assert!(
            page_url("https://example.com", "kalshi", "abc+/=")
                .unwrap()
                .as_str()
                .contains("cursor=abc%2B%2F%3D")
        );
    }
    #[test]
    fn skips_unsupported_but_rejects_malformed_or_nonadvancing_pages() {
        let old = ScanState {
            cursor: "stuck".into(),
            ..ScanState::default()
        };
        let (_, page) = parse_page(
            "polymarket",
            &json!({"markets":[{},{}]}),
            &old,
            &policy(),
            1,
            "fixture",
        )
        .unwrap();
        assert_eq!(page["skipped"], 2);
        assert_eq!(page["accepted"], 0);
        for data in [
            json!({}),
            json!({"markets":[],"next_cursor":123}),
            json!({"markets":[{}],"next_cursor":"stuck"}),
        ] {
            assert!(parse_page("polymarket", &data, &old, &policy(), 1, "fixture").is_err());
        }
    }
}
