//! Validated, versioned operator selections. Empty managed lists intentionally pause collection.
use crate::spool::Error;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Selection {
    pub schema_version: u8,
    pub revision: u64,
    pub enabled: bool,
    pub universe: BTreeMap<String, Vec<String>>,
}

impl Selection {
    pub fn parse(raw: &[u8]) -> Result<Self, Error> {
        if raw.len() > 65536 {
            return Err("selection payload too large".into());
        }
        let value: Self = serde_json::from_slice(raw)?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if self.schema_version != 1 || self.revision == 0 || self.universe.len() != 2 {
            return Err("invalid selection version or platforms".into());
        }
        for platform in ["polymarket", "kalshi"] {
            let ids = self.universe.get(platform).ok_or("missing platform")?;
            let unique: BTreeSet<_> = ids.iter().collect();
            if ids.len() > 50 || unique.len() != ids.len() {
                return Err("selection exceeds limit or contains duplicates".into());
            }
            for id in ids {
                let valid = !id.is_empty()
                    && id.len() <= 255
                    && if platform == "polymarket" {
                        id.bytes().all(|b| b.is_ascii_digit())
                    } else {
                        id.bytes()
                            .next()
                            .is_some_and(|b| b.is_ascii_uppercase() || b.is_ascii_digit())
                            && id.bytes().all(|b| {
                                b.is_ascii_uppercase() || b.is_ascii_digit() || b"._-".contains(&b)
                            })
                    };
                if !valid {
                    return Err("invalid exchange market identifier".into());
                }
            }
        }
        Ok(())
    }

    pub fn supersedes(&self, previous: Option<&Self>) -> Result<bool, Error> {
        self.validate()?;
        match previous {
            Some(old) if self.revision < old.revision => Err("older selection revision".into()),
            Some(old) if self.revision == old.revision && self != old => {
                Err("conflicting selection revision".into())
            }
            Some(old) if self == old => Ok(false),
            _ => Ok(true),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn value() -> serde_json::Value {
        json!({"schema_version":1,"revision":1,"enabled":true,"universe":{"polymarket":["123"],"kalshi":["KXFED-26OCT-H0"]}})
    }

    #[test]
    fn validates_ids_bounds_schema_and_explicit_empty_lists() {
        let mut valid = value();
        valid["universe"]["kalshi"] = json!([]);
        valid["universe"]["polymarket"] = json!([]);
        assert!(
            Selection::parse(valid.to_string().as_bytes())
                .unwrap()
                .enabled
        );
        for (pointer, bad) in [
            ("/schema_version", json!(2)),
            ("/revision", json!(0)),
            ("/universe/kalshi", json!(["../secrets"])),
            ("/universe/polymarket", json!(["1", "1"])),
            (
                "/universe/kalshi",
                json!((0..51).map(|i| format!("ID-{i}")).collect::<Vec<_>>()),
            ),
        ] {
            let mut invalid = value();
            *invalid.pointer_mut(pointer).unwrap() = bad;
            assert!(Selection::parse(invalid.to_string().as_bytes()).is_err());
        }
        let mut invalid = value();
        invalid["universe"]
            .as_object_mut()
            .unwrap()
            .remove("kalshi");
        assert!(Selection::parse(invalid.to_string().as_bytes()).is_err());
        assert!(Selection::parse(&vec![b' '; 65537]).is_err());
    }

    #[test]
    fn rejects_rollback_and_revision_conflict() {
        let original = Selection::parse(value().to_string().as_bytes()).unwrap();
        assert!(!original.supersedes(Some(&original)).unwrap());
        let mut changed = original.clone();
        changed.enabled = false;
        assert!(changed.supersedes(Some(&original)).is_err());
        changed.revision = 2;
        assert!(changed.supersedes(Some(&original)).unwrap());
        assert!(original.supersedes(Some(&changed)).is_err());
    }
}
