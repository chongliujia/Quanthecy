use quanthecy_market_data::{selection::Selection, spool::Spool};
use serde_json::json;

#[test]
fn persists_last_good_plan_and_preserves_legacy_universe() {
    let directory =
        std::env::temp_dir().join(format!("quanthecy-selection-{}", uuid::Uuid::new_v4()));
    let original = json!({"schema_version":1,"revision":8,"enabled":true,"universe":{"polymarket":["123"],"kalshi":[]}});
    {
        let mut spool = Spool::open(&directory).unwrap();
        spool
            .journal
            .universe
            .insert("polymarket".into(), vec!["999".into()]);
        spool
            .apply_selection(Selection::parse(original.to_string().as_bytes()).unwrap())
            .unwrap();
        let mut bad = original.clone();
        bad["universe"]["polymarket"] = json!(["456"]);
        assert!(
            spool
                .apply_selection(Selection::parse(bad.to_string().as_bytes()).unwrap())
                .is_err()
        );
        assert_eq!(
            spool.journal.selection.as_ref().unwrap().universe["polymarket"],
            vec!["123"]
        );
    }
    {
        let mut restarted = Spool::open(&directory).unwrap();
        assert_eq!(restarted.journal.selection.as_ref().unwrap().revision, 8);
        assert_eq!(restarted.journal.universe["polymarket"], vec!["999"]);
        let mut paused = original.clone();
        paused["revision"] = json!(9);
        paused["universe"]["polymarket"] = json!([]);
        restarted
            .apply_selection(Selection::parse(paused.to_string().as_bytes()).unwrap())
            .unwrap();
    }
    {
        let restarted = Spool::open(&directory).unwrap();
        let selection = restarted.journal.selection.as_ref().unwrap();
        assert!(selection.enabled);
        assert!(selection.universe.values().all(Vec::is_empty));
    }
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn reads_journals_from_before_managed_selection() {
    let directory = std::env::temp_dir().join(format!("quanthecy-legacy-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&directory).unwrap();
    let old = json!({"collector_id":uuid::Uuid::new_v4(),"batch_id":2,"universe":{"polymarket":["123"]},"latest":{},"pending":[],"raw":[]});
    std::fs::write(directory.join("journal.json"), old.to_string()).unwrap();
    {
        let spool = Spool::open(&directory).unwrap();
        assert!(spool.journal.selection.is_none());
        assert_eq!(spool.journal.batch_id, 2);
    }
    std::fs::remove_dir_all(directory).unwrap();
}
