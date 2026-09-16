use chrono::{Duration, Utc};
use quanthecy_market_data::{
    adapters::{continuity, normalize, stable_id},
    spool::Spool,
    validate_observation,
};
use serde_json::{Value, json};
use uuid::Uuid;

fn raw(platform: &str) -> Value {
    serde_json::from_str(if platform == "polymarket" {
        include_str!("../../../tests/fixtures/polymarket/market-rest.json")
    } else {
        include_str!("../../../tests/fixtures/kalshi/market-rest.json")
    })
    .unwrap()
}

#[test]
fn parses_public_exchange_snapshots_and_keeps_units_distinct() {
    for (platform, unit) in [("polymarket", "USD"), ("kalshi", "CONTRACTS")] {
        let observation = normalize(
            platform,
            &raw(platform),
            Utc::now(),
            "https://example.com/markets",
        )
        .unwrap();
        validate_observation(&observation).unwrap();
        assert_eq!(observation["volume"]["unit"], unit);
        assert!(observation["event_at"].is_null());
        assert!(observation["liquidity"].is_null());
        assert_eq!(observation["probability"]["basis"], "MIDPOINT");
    }
}

#[test]
fn missing_and_malformed_prices_are_not_zero_and_crossed_books_have_no_midpoint() {
    let mut market = raw("polymarket");
    market["bestBid"] = json!("not-a-number");
    let observation = normalize("polymarket", &market, Utc::now(), "REST").unwrap();
    assert!(observation["best_bid"].is_null());
    assert!(observation["probability"].is_null());
    assert!(
        observation["quality_flags"]
            .as_array()
            .unwrap()
            .contains(&json!("PARTIAL"))
    );
    market["bestBid"] = json!(0.9);
    let observation = normalize("polymarket", &market, Utc::now(), "REST").unwrap();
    assert!(observation["probability"].is_null());
    assert!(
        observation["quality_flags"]
            .as_array()
            .unwrap()
            .contains(&json!("CROSSED_BOOK"))
    );
}

#[test]
fn rejects_unsupported_contracts_and_does_not_turn_zero_size_into_probability() {
    let mut market = raw("kalshi");
    market["notional_value_dollars"] = json!("100.0000");
    assert!(normalize("kalshi", &market, Utc::now(), "REST").is_err());
    market["notional_value_dollars"] = json!("1.0000");
    market["yes_ask_size_fp"] = json!("0.00");
    let observation = normalize("kalshi", &market, Utc::now(), "REST").unwrap();
    assert!(observation["best_ask"].is_null());
    assert!(observation["probability"].is_null());
    market["ticker"] = Value::Null;
    assert!(normalize("kalshi", &market, Utc::now(), "REST").is_err());
}

#[test]
fn duplicate_payload_at_same_observation_time_has_same_identity() {
    let at = Utc::now();
    let a = normalize("polymarket", &raw("polymarket"), at, "REST").unwrap();
    let b = normalize("polymarket", &raw("polymarket"), at, "REST").unwrap();
    assert_eq!(a, b);
    assert_ne!(a["market"]["id"], stable_id("kalshi", "market", "559651"));
}

#[test]
fn gap_and_out_of_order_are_explicit() {
    let at = Utc::now();
    let old = normalize("polymarket", &raw("polymarket"), at, "REST").unwrap();
    for (delta, flag) in [(300, "GAP"), (-1, "OUT_OF_ORDER")] {
        let mut next = normalize(
            "polymarket",
            &raw("polymarket"),
            at + Duration::seconds(delta),
            "REST",
        )
        .unwrap();
        continuity(&old, &mut next, 60);
        assert!(
            next["quality_flags"]
                .as_array()
                .unwrap()
                .contains(&json!(flag))
        );
    }
}

#[test]
fn pending_batch_survives_restart_and_single_writer_lock() {
    let directory = std::env::temp_dir().join(format!("quanthecy-spool-test-{}", Uuid::new_v4()));
    let mut spool = Spool::open(&directory).unwrap();
    assert!(Spool::open(&directory).is_err());
    let observation = normalize("polymarket", &raw("polymarket"), Utc::now(), "REST").unwrap();
    let collector = spool.journal.collector_id;
    spool
        .stage(vec![observation.clone()], vec![raw("polymarket")])
        .unwrap();
    assert!(
        spool
            .stage(vec![observation.clone()], vec![raw("polymarket")])
            .is_err()
    );
    drop(spool);
    let mut recovered = Spool::open(&directory).unwrap();
    assert_eq!(recovered.journal.collector_id, collector);
    assert_eq!(recovered.journal.batch_id, 1);
    assert_eq!(recovered.journal.pending, vec![observation]);
    recovered.acknowledge().unwrap();
    drop(recovered);
    let acknowledged = Spool::open(&directory).unwrap();
    assert!(acknowledged.journal.pending.is_empty());
    assert_eq!(acknowledged.journal.latest.len(), 1);
    drop(acknowledged);
    std::fs::remove_dir_all(directory).unwrap();
}
