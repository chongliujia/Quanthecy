use jsonschema::Validator;
use serde_json::Value;
use std::sync::LazyLock;

pub mod adapters;
pub mod collector;
pub mod selection;
pub mod spool;

static CONTRACT: LazyLock<Validator> = LazyLock::new(|| {
    let schema: Value = serde_json::from_str(include_str!(
        "../../../contracts/v1/market-observation.schema.json"
    ))
    .expect("checked-in schema is valid JSON");
    jsonschema::options()
        .should_validate_formats(true)
        .build(&schema)
        .expect("checked-in schema compiles")
});

pub fn validate_observation(value: &Value) -> Result<(), String> {
    CONTRACT.validate(value).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const POLYMARKET: &str = include_str!("../../../tests/fixtures/polymarket/observation.json");
    const KALSHI: &str = include_str!("../../../tests/fixtures/kalshi/observation.json");

    #[test]
    fn accepts_both_platform_contract_fixtures() {
        for fixture in [POLYMARKET, KALSHI] {
            validate_observation(&serde_json::from_str(fixture).unwrap()).unwrap();
        }
    }

    #[test]
    fn rejects_shared_invalid_cases() {
        let base: Value = serde_json::from_str(POLYMARKET).unwrap();
        let cases: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/invalid-observations.json"
        ))
        .unwrap();
        for case in cases.as_array().unwrap() {
            let mut value = base.clone();
            *value.pointer_mut(case["path"].as_str().unwrap()).unwrap() = case["value"].clone();
            assert!(validate_observation(&value).is_err(), "{}", case["name"]);
        }
    }

    #[test]
    fn rejects_unknown_fields() {
        let mut value: Value = serde_json::from_str(POLYMARKET).unwrap();
        value["probability"]["untrusted_extra"] = Value::Bool(true);
        assert!(validate_observation(&value).is_err());
    }
}
