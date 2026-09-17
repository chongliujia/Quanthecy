//! A single durable, locked collector journal. A pending batch is replayed before new collection.
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
use uuid::Uuid;

pub type Error = Box<dyn std::error::Error + Send + Sync>;

#[derive(Clone, Default, Serialize, Deserialize)]
pub struct Journal {
    pub collector_id: Uuid,
    pub batch_id: u64,
    pub universe: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub selection: Option<crate::selection::Selection>,
    pub latest: BTreeMap<String, Value>,
    pub pending: Vec<Value>,
    pub raw: Vec<Value>,
    #[serde(default)]
    pub catalog: BTreeMap<String, crate::catalog::ScanState>,
    #[serde(default)]
    pub catalog_page_id: u64,
    #[serde(default)]
    pub catalog_pending: Option<Value>,
}

pub struct Spool {
    pub journal: Journal,
    path: PathBuf,
    _lock: File,
}

impl Spool {
    pub fn open(directory: &Path) -> Result<Self, Error> {
        fs::create_dir_all(directory)?;
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(directory.join("lock"))?;
        lock.try_lock_exclusive()?;
        let path = directory.join("journal.json");
        let journal = if path.exists() {
            serde_json::from_slice(&fs::read(&path)?)?
        } else {
            Journal {
                collector_id: Uuid::new_v4(),
                ..Journal::default()
            }
        };
        if let Some(selection) = &journal.selection {
            selection.validate()?;
        }
        let spool = Self {
            journal,
            path,
            _lock: lock,
        };
        spool.save()?;
        Ok(spool)
    }

    pub fn save(&self) -> Result<(), Error> {
        let temporary = self.path.with_extension("tmp");
        let mut file = File::create(&temporary)?;
        file.write_all(&serde_json::to_vec(&self.journal)?)?;
        file.sync_all()?;
        fs::rename(temporary, &self.path)?;
        File::open(self.path.parent().expect("spool directory"))?.sync_all()?;
        Ok(())
    }

    pub fn apply_selection(&mut self, selection: crate::selection::Selection) -> Result<(), Error> {
        if !selection.supersedes(self.journal.selection.as_ref())? {
            return Ok(());
        }
        let previous = self.journal.selection.replace(selection);
        if let Err(error) = self.save() {
            self.journal.selection = previous;
            return Err(error);
        }
        Ok(())
    }

    pub fn stage(&mut self, observations: Vec<Value>, raw: Vec<Value>) -> Result<(), Error> {
        if !self.journal.pending.is_empty() {
            return Err("pending batch must be delivered first".into());
        }
        if observations.is_empty() || observations.len() != raw.len() {
            return Err("invalid batch".into());
        }
        self.journal.batch_id += 1;
        self.journal.pending = observations;
        self.journal.raw = raw;
        self.save()
    }

    pub fn acknowledge(&mut self) -> Result<(), Error> {
        for value in &self.journal.pending {
            self.journal.latest.insert(
                value["market"]["id"].as_str().ok_or("market id")?.into(),
                value.clone(),
            );
        }
        self.journal.pending.clear();
        self.journal.raw.clear();
        self.save()
    }
}
