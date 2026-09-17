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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sources: Option<BTreeMap<String, SourceControl>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intervals: Option<BTreeMap<String, BTreeMap<String, u64>>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub discovery: Option<DiscoveryControl>,
}

impl Selection {
    pub fn parse(raw: &[u8]) -> Result<Self, Error> {
        if raw.len() > 524288 {
            return Err("selection payload too large".into());
        }
        let value: Self = serde_json::from_slice(raw)?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if ![1, 2, 3].contains(&self.schema_version)
            || self.revision == 0
            || self.universe.len() != 2
        {
            return Err("invalid selection version or platforms".into());
        }
        match (&self.sources, self.schema_version) {
            (None, 1) => {}
            (Some(sources), 2 | 3) if sources.len() == 2 => {
                for platform in ["polymarket", "kalshi"] {
                    let control = sources.get(platform).ok_or("missing source control")?;
                    if !(15..=3600).contains(&control.interval_seconds) {
                        return Err("invalid collection interval".into());
                    }
                }
            }
            _ => return Err("invalid source control schema".into()),
        }
        for platform in ["polymarket", "kalshi"] {
            let ids = self.universe.get(platform).ok_or("missing platform")?;
            let unique: BTreeSet<_> = ids.iter().collect();
            if ids.len() > (if self.schema_version == 3 { 250 } else { 50 })
                || unique.len() != ids.len()
            {
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
        match (&self.discovery, &self.intervals, self.schema_version) {
            (Some(discovery), Some(intervals), 3) if intervals.len() == 2 => {
                discovery.validate()?;
                for (platform, ids) in &self.universe {
                    let schedule = intervals.get(platform).ok_or("missing market intervals")?;
                    if schedule.len() != ids.len()
                        || ids
                            .iter()
                            .any(|id| !schedule.get(id).is_some_and(|n| (15..=3600).contains(n)))
                    {
                        return Err("invalid market intervals".into());
                    }
                }
            }
            (None, None, 1 | 2) => {}
            _ => return Err("invalid discovery schema".into()),
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

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceControl {
    pub enabled: bool,
    pub interval_seconds: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DiscoveryControl {
    pub enabled: bool,
    pub interval_seconds: u64,
    pub page_interval_seconds: u64,
    pub max_pages: u32,
}

impl DiscoveryControl {
    fn validate(&self) -> Result<(), Error> {
        if !(300..=86400).contains(&self.interval_seconds)
            || !(5..=300).contains(&self.page_interval_seconds)
            || !(1..=1000).contains(&self.max_pages)
        {
            return Err("invalid discovery bounds".into());
        }
        Ok(())
    }
}

/// Independent source schedules; configuration changes and resume take effect immediately.
#[derive(Default)]
pub struct Schedule {
    sources: BTreeMap<String, (SourceControl, std::time::Instant)>,
}

impl Schedule {
    pub fn claim(
        &mut self,
        platform: &str,
        control: &SourceControl,
        now: std::time::Instant,
    ) -> bool {
        if let Some((old, due)) = self.sources.get(platform)
            && old == control
            && now < *due
        {
            return false;
        }
        self.sources.insert(
            platform.into(),
            (
                control.clone(),
                now + std::time::Duration::from_secs(control.interval_seconds),
            ),
        );
        control.enabled
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
        assert!(Selection::parse(&vec![b' '; 524289]).is_err());
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

#[cfg(test)]
mod control_tests {
    use super::*;
    use serde_json::json;
    use std::time::{Duration, Instant};

    #[test]
    fn v3_requires_exact_bounded_interval_maps_and_discovery_policy() {
        let good = json!({"schema_version":3,"revision":3,"enabled":true,
            "universe":{"polymarket":["123"],"kalshi":[]},
            "sources":{"polymarket":{"enabled":true,"interval_seconds":60},"kalshi":{"enabled":false,"interval_seconds":60}},
            "intervals":{"polymarket":{"123":300},"kalshi":{}},
            "discovery":{"enabled":true,"interval_seconds":3600,"page_interval_seconds":10,"max_pages":200}});
        assert!(Selection::parse(good.to_string().as_bytes()).is_ok());
        for (pointer, value) in [
            ("/intervals/polymarket", json!({})),
            ("/discovery/max_pages", json!(1001)),
            ("/discovery/page_interval_seconds", json!(0)),
            ("/schema_version", json!(2)),
        ] {
            let mut bad = good.clone();
            *bad.pointer_mut(pointer).unwrap() = value;
            assert!(Selection::parse(bad.to_string().as_bytes()).is_err());
        }
    }

    #[test]
    fn runtime_schema_requires_both_bounded_sources() {
        let valid = json!({"schema_version":2,"revision":2,"enabled":false,
            "universe":{"polymarket":[],"kalshi":[]},
            "sources":{"polymarket":{"enabled":false,"interval_seconds":15},"kalshi":{"enabled":true,"interval_seconds":3600}}});
        assert!(Selection::parse(valid.to_string().as_bytes()).is_ok());
        for (pointer, value) in [
            ("/sources/polymarket/interval_seconds", json!(14)),
            ("/sources/kalshi/interval_seconds", json!(3601)),
            ("/sources/kalshi/enabled", json!("false")),
            ("/schema_version", json!(1)),
            ("/sources", json!({})),
        ] {
            let mut invalid = valid.clone();
            *invalid.pointer_mut(pointer).unwrap() = value;
            assert!(Selection::parse(invalid.to_string().as_bytes()).is_err());
        }
    }

    #[test]
    fn frequencies_are_independent_and_resume_is_immediate() {
        let now = Instant::now();
        let fast = SourceControl {
            enabled: true,
            interval_seconds: 15,
        };
        let slow = SourceControl {
            enabled: true,
            interval_seconds: 3600,
        };
        let paused = SourceControl {
            enabled: false,
            interval_seconds: 3600,
        };
        let mut schedule = Schedule::default();
        assert!(schedule.claim("polymarket", &fast, now));
        assert!(schedule.claim("kalshi", &slow, now));
        assert!(!schedule.claim("polymarket", &fast, now + Duration::from_secs(14)));
        assert!(schedule.claim("polymarket", &fast, now + Duration::from_secs(15)));
        assert!(!schedule.claim("kalshi", &slow, now + Duration::from_secs(15)));
        assert!(!schedule.claim("kalshi", &paused, now + Duration::from_secs(16)));
        assert!(schedule.claim("kalshi", &slow, now + Duration::from_secs(17)));
        // Frequency edits take effect without waiting for the old long interval.
        assert!(schedule.claim("kalshi", &fast, now + Duration::from_secs(18)));
    }
}
