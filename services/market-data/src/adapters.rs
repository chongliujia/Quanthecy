//! REST snapshots of the YES outcome of binary markets. No synthetic trade prices.
use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use uuid::Uuid;

pub fn stable_id(platform: &str, kind: &str, external: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("https://quanthecy.org/identity/v1/{platform}/{kind}/{external}").as_bytes(),
    )
    .to_string()
}

pub fn timestamp(time: DateTime<Utc>) -> String {
    time.to_rfc3339_opts(SecondsFormat::Micros, true)
}

fn time(value: &Value) -> Value {
    value
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|t| json!(timestamp(t.with_timezone(&Utc))))
        .unwrap_or(Value::Null)
}

fn required<'a>(value: &'a Value, field: &str) -> Result<&'a str, String> {
    value[field]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| format!("missing {field}"))
}

pub fn number(value: &Value) -> Option<f64> {
    let n = value.as_f64().or_else(|| value.as_str()?.parse().ok())?;
    (n.is_finite() && n >= 0.0).then_some(n)
}

fn array(value: &Value) -> Result<Vec<Value>, String> {
    let parsed = if let Some(s) = value.as_str() {
        serde_json::from_str(s).map_err(|_| "malformed array")?
    } else {
        value.clone()
    };
    parsed
        .as_array()
        .cloned()
        .ok_or_else(|| "missing array".into())
}

pub fn normalize(
    platform: &str,
    raw: &Value,
    received: DateTime<Utc>,
    source: &str,
) -> Result<Value, String> {
    let (
        market,
        event,
        event_title,
        title,
        outcome,
        rules,
        status,
        bid,
        ask,
        volume,
        unit,
        open,
        close,
        resolved,
        result,
    ) = match platform {
        "polymarket" => {
            let outcomes = array(&raw["outcomes"])?;
            if outcomes != vec![json!("Yes"), json!("No")] {
                return Err("only Yes/No binary markets supported".into());
            }
            let tokens = array(&raw["clobTokenIds"])?;
            let outcome = tokens
                .first()
                .and_then(Value::as_str)
                .ok_or("missing YES token")?
                .to_owned();
            let event = raw["events"]
                .as_array()
                .and_then(|v| v.first())
                .ok_or("missing event")?;
            let status = if raw["umaResolutionStatus"] == "resolved" {
                "RESOLVED"
            } else if raw["closed"] == true {
                "CLOSED"
            } else if raw["active"] == true {
                "OPEN"
            } else {
                "UNKNOWN"
            };
            (
                required(raw, "id")?,
                required(event, "id")?,
                required(event, "title")?,
                required(raw, "question")?,
                outcome,
                raw["description"].as_str().unwrap_or("").to_owned(),
                status,
                number(&raw["bestBid"]),
                number(&raw["bestAsk"]),
                number(&raw["volume"]),
                "USD",
                time(&raw["startDate"]),
                time(&raw["endDate"]),
                Value::Null,
                "UNKNOWN",
            )
        }
        "kalshi" => {
            if raw["market_type"] != "binary" || number(&raw["notional_value_dollars"]) != Some(1.0)
            {
                return Err("only binary one-dollar contracts supported".into());
            }
            let market = required(raw, "ticker")?;
            let status = match raw["status"].as_str().unwrap_or("") {
                "active" => "OPEN",
                "closed" | "determined" | "disputed" | "amended" => "CLOSED",
                "finalized" => "RESOLVED",
                _ => "UNKNOWN",
            };
            let result = if status == "RESOLVED" {
                match raw["result"].as_str() {
                    Some("yes") => "WON",
                    Some("no") => "LOST",
                    _ => "UNKNOWN",
                }
            } else {
                "UNKNOWN"
            };
            let bid = number(&raw["yes_bid_dollars"])
                .filter(|_| number(&raw["yes_bid_size_fp"]).is_some_and(|s| s > 0.0));
            let ask = number(&raw["yes_ask_dollars"])
                .filter(|_| number(&raw["yes_ask_size_fp"]).is_some_and(|s| s > 0.0));
            (
                market,
                required(raw, "event_ticker")?,
                raw["event_title"]
                    .as_str()
                    .unwrap_or(required(raw, "event_ticker")?),
                raw["title"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .unwrap_or(market),
                format!("{market}:yes"),
                format!(
                    "{}\n\n{}",
                    raw["rules_primary"].as_str().unwrap_or(""),
                    raw["rules_secondary"].as_str().unwrap_or("")
                ),
                status,
                bid,
                ask,
                number(&raw["volume_fp"]),
                "CONTRACTS",
                time(&raw["open_time"]),
                time(&raw["close_time"]),
                time(&raw["settlement_ts"]),
                result,
            )
        }
        _ => return Err("unknown platform".into()),
    };
    // Zero/one quotes can be API sentinels. Only interior two-sided quotes produce a midpoint.
    let bid = bid.filter(|n| *n > 0.0 && *n < 1.0);
    let ask = ask.filter(|n| *n > 0.0 && *n < 1.0);
    let mut flags = vec!["SOURCE_TIME_MISSING"];
    if bid.is_none() || ask.is_none() || volume.is_none() || rules.trim().is_empty() {
        flags.push("PARTIAL");
    }
    let midpoint = match (bid, ask) {
        (Some(b), Some(a)) if b <= a && status == "OPEN" => Some((b + a) / 2.0),
        (Some(b), Some(a)) if b > a => {
            flags.push("CROSSED_BOOK");
            None
        }
        _ => None,
    };
    let received_at = timestamp(received);
    let raw_json = serde_json::to_vec(raw).map_err(|e| e.to_string())?;
    let hash = format!("{:x}", Sha256::digest(raw_json));
    let rule_content = json!({"title":title,"rules":rules,"closes_at":close,
        "resolution_source":raw["resolutionSource"],"outcome":outcome});
    let rule_hash = format!("{:x}", Sha256::digest(rule_content.to_string().as_bytes()));
    let observation_id = stable_id(
        platform,
        "observation",
        &format!("{market}/{received_at}/{hash}"),
    );
    let observation = json!({
        "schema_version":"1.0.0", "observation_id":observation_id, "platform":platform,
        "event":{"id":stable_id(platform,"event",event),"exchange_id":event,"title":event_title},
        "market":{"id":stable_id(platform,"market",market),"exchange_id":market,"title":title,"description":rules,
            "status":status,"rules_version":rule_hash,"resolution_rules":rules,
            "resolution_source":raw["resolutionSource"].as_str().filter(|s| !s.is_empty()),
            "opens_at":open,"closes_at":close,"resolved_at":resolved},
        "outcome":{"id":stable_id(platform,"outcome",&outcome),"exchange_id":outcome,"label":"Yes","result":result},
        "event_at":null,"received_at":received_at,"recorded_at":received_at,
        "probability":midpoint.map(|p| json!({"value":p,"basis":"MIDPOINT","source":format!("{platform}:REST:yes_bid_ask"),"as_of":received_at})),
        "best_bid":bid,"best_ask":ask,
        "volume":volume.map(|v| json!({"value":v,"unit":unit,"basis":format!("{platform}:reported_cumulative_volume"),"window_start":null,"as_of":received_at})),
        "liquidity":null,"quality_flags":flags,
        "provenance":{"transport":"REST","source":source,"source_event_id":null,"sequence":null,"payload_sha256":hash}
    });
    crate::validate_observation(&observation)?;
    Ok(observation)
}

/// Return a flag instead of rewriting collection timestamps or filling missing intervals.
pub fn continuity(previous: &Value, current: &mut Value, interval_seconds: i64) {
    let parse = |v: &Value| {
        v["received_at"]
            .as_str()
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
    };
    if let (Some(old), Some(new)) = (parse(previous), parse(current)) {
        let flag = if new <= old {
            Some("OUT_OF_ORDER")
        } else if (new - old).num_seconds() > interval_seconds * 2 + 30 {
            Some("GAP")
        } else {
            None
        };
        if let Some(flag) = flag {
            current["quality_flags"]
                .as_array_mut()
                .expect("normalized flags")
                .push(json!(flag));
        }
    }
}
