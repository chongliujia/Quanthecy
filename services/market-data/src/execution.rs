//! Public order-book snapshots for paper execution; this module cannot submit orders.
use crate::{
    adapters::{number, stable_id, timestamp},
    collector::Collector,
    spool::Error,
};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};
use tokio::sync::watch;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Target {
    market_id: String,
    platform: String,
    exchange_id: String,
    outcome_id: String,
}

pub fn targets(raw: &[u8]) -> Result<Vec<Target>, Error> {
    if raw.len() > 32768 {
        return Err("execution universe too large".into());
    }
    if raw.is_empty() {
        return Ok(Vec::new());
    }
    let rows: Vec<Target> = serde_json::from_slice(raw)?;
    if rows.len() > 20 {
        return Err("execution universe exceeds 20 markets".into());
    }
    let mut seen = BTreeSet::new();
    for row in &rows {
        let valid = if row.platform == "polymarket" {
            !row.outcome_id.is_empty()
                && row.outcome_id.bytes().all(|b| b.is_ascii_digit())
                && row.exchange_id.bytes().all(|b| b.is_ascii_digit())
        } else {
            row.platform == "kalshi"
                && row.outcome_id == format!("{}:yes", row.exchange_id)
                && row
                    .exchange_id
                    .bytes()
                    .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b"._-".contains(&b))
        };
        if !valid
            || row.exchange_id.is_empty()
            || row.exchange_id.len() > 255
            || row.outcome_id.len() > 255
            || row.market_id != stable_id(&row.platform, "market", &row.exchange_id)
            || !seen.insert(&row.market_id)
        {
            return Err("invalid execution target".into());
        }
    }
    Ok(rows)
}

fn levels(
    raw: &Value,
    kalshi: bool,
    complement: bool,
    descending: bool,
) -> Result<Vec<Value>, Error> {
    let rows = raw.as_array().ok_or("missing order-book side")?;
    if rows.len() > 10000 {
        return Err("order-book side too large".into());
    }
    let mut values = Vec::new();
    for row in rows {
        let (price, size) = if kalshi {
            (number(&row[0]), number(&row[1]))
        } else {
            (number(&row["price"]), number(&row["size"]))
        };
        let (Some(mut price), Some(size)) = (price, size) else {
            return Err("invalid book level".into());
        };
        if complement {
            price = 1.0 - price;
        }
        if price > 0.0 && price < 1.0 && size > 0.0 {
            values.push((price, size));
        }
    }
    values.sort_by(|a, b| {
        if descending {
            b.0.total_cmp(&a.0)
        } else {
            a.0.total_cmp(&b.0)
        }
    });
    values.truncate(100);
    Ok(values
        .into_iter()
        .map(|(p, s)| json!({"price":format!("{p:.6}"),"size":format!("{s:.6}")}))
        .collect())
}

pub fn normalize_book(platform: &str, book: &Value) -> Result<(Vec<Value>, Vec<Value>), Error> {
    let (bids, asks) = if platform == "kalshi" {
        (
            levels(&book["orderbook_fp"]["yes_dollars"], true, false, true)?,
            levels(&book["orderbook_fp"]["no_dollars"], true, true, false)?,
        )
    } else {
        (
            levels(&book["bids"], false, false, true)?,
            levels(&book["asks"], false, false, false)?,
        )
    };
    if let (Some(bid), Some(ask)) = (bids.first(), asks.first())
        && number(&bid["price"]) > number(&ask["price"])
    {
        return Err("crossed execution order book".into());
    }
    Ok((bids, asks))
}

pub fn fee_parameters(platform: &str, metadata: &Value) -> (Option<f64>, &'static str) {
    if platform == "polymarket" {
        if metadata["feesEnabled"] == false {
            return (Some(0.0), "polymarket_quadratic");
        }
        if metadata["feesEnabled"] == true
            && number(&metadata["feeSchedule"]["exponent"]) == Some(1.0)
            && let Some(rate) = number(&metadata["feeSchedule"]["rate"]).filter(|r| *r <= 1.0)
        {
            return (Some(rate), "polymarket_quadratic");
        }
    } else if matches!(
        metadata["fee_type"].as_str(),
        Some("quadratic" | "quadratic_with_maker_fees")
    ) && let Some(multiplier) = number(&metadata["fee_multiplier"]).filter(|m| *m <= 10.0)
    {
        return (Some(0.07 * multiplier), "kalshi_quadratic");
    }
    (None, "unknown")
}

fn polymarket_payout(market: &Value, outcome: &str) -> Option<i32> {
    let resolved = &market["paper_resolution"];
    if market["umaResolutionStatus"] != "resolved"
        || market["closed"] != true
        || resolved["closed"] != true
        || resolved["condition_id"] != market["conditionId"]
    {
        return None;
    }
    let tokens = resolved["tokens"].as_array()?;
    if tokens.len() != 2
        || tokens.iter().filter(|t| t["winner"] == true).count() != 1
        || tokens.iter().any(|t| !t["winner"].is_boolean())
    {
        return None;
    }
    let yes = tokens
        .iter()
        .find(|t| t["token_id"] == outcome && t["outcome"] == "Yes")?;
    if !tokens
        .iter()
        .any(|t| t["outcome"] == "No" && t["token_id"] != outcome)
    {
        return None;
    }
    Some(i32::from(yes["winner"].as_bool()?))
}

async fn deliver(collector: &mut Collector) -> Result<(), Error> {
    if collector.spool.journal.execution_pending.is_empty() {
        return Ok(());
    }
    let rows: Vec<String> = collector.spool.journal.execution_pending.iter().map(|row| json!({
        "quote_id":row["quote_id"],"market_id":row["market_id"],"platform":row["platform"],"received_at":row["received_at"],"envelope":row.to_string()
    }).to_string()).collect();
    collector
        .ch(
            "INSERT INTO execution_quotes FORMAT JSONEachRow",
            rows.join("\n"),
        )
        .await?;
    collector.spool.journal.execution_pending.clear();
    collector.spool.save()
}

async fn snapshot(
    collector: &Collector,
    target: &Target,
    cached: &mut BTreeMap<String, (DateTime<Utc>, Value, Value)>,
) -> Result<Value, Error> {
    let clob = std::env::var("POLYMARKET_CLOB_URL")
        .unwrap_or_else(|_| "https://clob.polymarket.com".into());
    let metadata_url = if target.platform == "polymarket" {
        format!(
            "{}/markets?id={}&limit=1",
            collector.poly_url, target.exchange_id
        )
    } else {
        format!("{}/markets/{}", collector.kalshi_url, target.exchange_id)
    };
    if cached
        .get(&target.market_id)
        .is_none_or(|(at, _, _)| (Utc::now() - *at).num_seconds() >= 60)
    {
        let data = collector.get(&metadata_url).await?;
        let mut market = if target.platform == "polymarket" {
            data.as_array()
                .and_then(|rows| rows.iter().find(|r| r["id"] == target.exchange_id))
                .cloned()
                .ok_or("market absent")?
        } else {
            data["market"].clone()
        };
        if target.platform == "polymarket"
            && market["closed"] == true
            && market["umaResolutionStatus"] == "resolved"
            && let Some(condition) = market["conditionId"].as_str()
            && condition.len() == 66
            && condition.starts_with("0x")
            && condition[2..].bytes().all(|b| b.is_ascii_hexdigit())
        {
            let source = format!("{clob}/markets/{condition}");
            if let Ok(result) = collector.get(&source).await {
                market["paper_resolution"] = result;
                market["paper_resolution_source"] = json!(source);
            }
        }
        let fees = if target.platform == "polymarket" {
            market.clone()
        } else {
            let series = target.exchange_id.split('-').next().ok_or("series")?;
            collector
                .get(&format!("{}/series/{series}", collector.kalshi_url))
                .await?["series"]
                .clone()
        };
        cached.insert(target.market_id.clone(), (Utc::now(), market, fees));
    }
    let (metadata_at, market, fees) = cached.get(&target.market_id).ok_or("metadata")?;
    let (status, settlement) = if target.platform == "polymarket" {
        let tokens: Value = if let Some(s) = market["clobTokenIds"].as_str() {
            serde_json::from_str(s)?
        } else {
            market["clobTokenIds"].clone()
        };
        if tokens[0] != target.outcome_id {
            return Err("YES token changed".into());
        }
        let payout = polymarket_payout(market, &target.outcome_id);
        (
            if payout.is_some() {
                "RESOLVED"
            } else if market["active"] == true
                && market["closed"] == false
                && market["acceptingOrders"] == true
            {
                "OPEN"
            } else {
                "CLOSED"
            },
            payout,
        )
    } else {
        if market["ticker"] != target.exchange_id {
            return Err("market identity mismatch".into());
        }
        match market["status"].as_str() {
            Some("active") => ("OPEN", None),
            Some("finalized") => (
                "RESOLVED",
                match market["result"].as_str() {
                    Some("yes") => Some(1),
                    Some("no") => Some(0),
                    _ => None,
                },
            ),
            _ => ("CLOSED", None),
        }
    };
    let source = if target.platform == "polymarket" {
        format!("{clob}/book?token_id={}", target.outcome_id)
    } else {
        format!(
            "{}/markets/{}/orderbook",
            collector.kalshi_url, target.exchange_id
        )
    };
    let book = if status == "OPEN" {
        collector.get(&source).await?
    } else {
        json!({})
    };
    if target.platform == "polymarket" && status == "OPEN" && book["asset_id"] != target.outcome_id
    {
        return Err("book token mismatch".into());
    }
    let (bids, asks) = if status == "OPEN" {
        normalize_book(&target.platform, &book)?
    } else {
        (vec![], vec![])
    };
    let (rate, model) = fee_parameters(&target.platform, fees);
    let received = Utc::now();
    let source_at = book["timestamp"]
        .as_str()
        .and_then(|s| s.parse::<i64>().ok())
        .and_then(DateTime::from_timestamp_millis)
        .map(timestamp);
    Ok(
        json!({"schema_version":1,"quote_id":uuid::Uuid::new_v4(),"market_id":target.market_id,
        "platform":target.platform,"exchange_id":target.exchange_id,"outcome_id":target.outcome_id,
        "received_at":timestamp(received),"recorded_at":timestamp(Utc::now()),"metadata_at":timestamp(*metadata_at),"source_at":source_at,
        "status":status,"settlement":settlement,"bids":bids,"asks":asks,"fee_rate":rate,"fee_model":model,
        "fee_source":if target.platform == "polymarket" { metadata_url.clone() } else { format!("{}/series/{}",collector.kalshi_url,target.exchange_id.split('-').next().unwrap_or("")) },
        "source":source,"raw":{"book":book,"metadata_source":metadata_url,"market_status":market["status"],"result":market["result"],"resolution":market["paper_resolution"],"resolution_source":market["paper_resolution_source"],"fee_schedule":fees["feeSchedule"],"fees_enabled":fees["feesEnabled"],"fee_type":fees["fee_type"],"fee_multiplier":fees["fee_multiplier"]}}),
    )
}

pub async fn run(mut collector: Collector, mut stop: watch::Receiver<bool>) {
    let mut cached = BTreeMap::new();
    loop {
        let work = async {
            deliver(&mut collector).await?;
            collector.refresh_configuration(false).await;
            let client = redis::Client::open(collector.redis_url.as_str())?;
            let mut connection = client.get_multiplexed_async_connection().await?;
            let raw: Vec<u8> = redis::cmd("GETRANGE")
                .arg("paper:universe:v1")
                .arg(0)
                .arg(32768)
                .query_async(&mut connection)
                .await?;
            let selected = targets(&raw)?;
            cached.retain(|key, _| selected.iter().any(|t| t.market_id == *key));
            let mut errors = 0;
            let mut successful = 0;
            for target in &selected {
                if !collector.control(&target.platform).enabled {
                    continue;
                }
                match snapshot(&collector, target, &mut cached).await {
                    Ok(row) => {
                        collector.spool.journal.execution_pending.push(row);
                        collector.spool.save()?;
                        successful += 1;
                    }
                    Err(_) => {
                        errors += 1;
                        tracing::warn!(platform=%target.platform,market=%target.exchange_id,"paper order-book snapshot unavailable");
                    }
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            deliver(&mut collector).await?;
            let telemetry = json!({"checked_at":timestamp(Utc::now()),"markets":selected.len(),"successful":successful,"errors":errors});
            redis::cmd("SET")
                .arg("paper:collector:status:v1")
                .arg(telemetry.to_string())
                .arg("EX")
                .arg(90)
                .query_async::<()>(&mut connection)
                .await?;
            Ok::<(), Error>(())
        };
        tokio::select! {
            _ = stop.changed() => break,
            result = tokio::time::timeout(Duration::from_secs(75),work) => if !matches!(result,Ok(Ok(()))) { tracing::warn!("paper order-book cycle interrupted; staged quotes retained"); }
        }
        tokio::select! { _ = stop.changed() => break, _ = tokio::time::sleep(Duration::from_secs(15)) => {} }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn settlement_requires_matching_final_binary_winner_not_price() {
        let mut market = json!({"closed":true,"umaResolutionStatus":"resolved","conditionId":"condition",
            "outcomePrices":["1","0"],"paper_resolution":{"closed":true,"condition_id":"condition",
            "tokens":[{"token_id":"yes","outcome":"Yes","winner":false},{"token_id":"no","outcome":"No","winner":false}]}});
        assert_eq!(polymarket_payout(&market, "yes"), None);
        market["paper_resolution"]["tokens"][1]["winner"] = json!(true);
        assert_eq!(polymarket_payout(&market, "yes"), Some(0));
        market["paper_resolution"]["tokens"][0]["winner"] = json!(true);
        assert_eq!(polymarket_payout(&market, "yes"), None);
        market["paper_resolution"]["tokens"][1]["winner"] = json!(false);
        assert_eq!(polymarket_payout(&market, "yes"), Some(1));
        market["paper_resolution"]["condition_id"] = json!("other");
        assert_eq!(polymarket_payout(&market, "yes"), None);
    }
    #[test]
    fn kalshi_complements_no_bids_and_sorts_best_prices_first() {
        let book = json!({"orderbook_fp":{"yes_dollars":[["0.20","80"],["0.40","20"]],"no_dollars":[["0.50","30"],["0.30","60"]]}});
        let (bids, asks) = normalize_book("kalshi", &book).unwrap();
        assert_eq!(bids[0]["price"], "0.400000");
        assert_eq!(asks[0], json!({"price":"0.500000","size":"30.000000"}));
    }
    #[test]
    fn invalid_books_and_unknown_fees_never_become_free_fills() {
        assert!(
            normalize_book(
                "polymarket",
                &json!({"bids":[{"price":"0.8","size":"5"}],"asks":[{"price":"0.7","size":"9"}]})
            )
            .is_err()
        );
        assert_eq!(fee_parameters("polymarket", &json!({})), (None, "unknown"));
        assert_eq!(
            fee_parameters(
                "polymarket",
                &json!({"feesEnabled":true,"feeSchedule":{"rate":0.03,"exponent":1}})
            ),
            (Some(0.03), "polymarket_quadratic")
        );
        assert_eq!(
            fee_parameters(
                "kalshi",
                &json!({"fee_type":"quadratic","fee_multiplier":0})
            ),
            (Some(0.0), "kalshi_quadratic")
        );
        assert!(targets(br#"[{"market_id":"wrong","platform":"kalshi","exchange_id":"../orders","outcome_id":"x"}]"#).is_err());
    }
}
