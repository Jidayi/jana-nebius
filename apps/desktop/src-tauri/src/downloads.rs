//! The shell's download manager (PLT-11, PLT-23; ARC-06 and ARC-08 through [`crate::net`]).
//!
//! Model packs, content packs and app updates download in chunks (`DOWNLOAD_CHUNK_MB`, proposal 8 MB) with HTTP range
//! requests. Every request goes through the shared egress policy first ([`net::check`]): the `downloads` feature must
//! be on, the host allow-listed and the network usable. Each chunk is checked against the sha256 the signed manifest
//! lists for it (the core verifies the manifest's signature before it hands the job over) and only then marked in the
//! journal, so after a crash, a restart or a lost connection the download resumes from the last verified chunk without
//! fetching it again. A chunk that fails its hash is fetched again, up to `DOWNLOAD_CHUNK_RETRIES` times; then the item
//! is `failed` with nothing installed. When every chunk is verified the whole file's sha256 is checked, and the files
//! are installed by one atomic rename of their folder into the target the core named.
//!
//! The states are those of FIGURE PLT-11a. Losing the network moves the item to `waiting_for_network` and keeps its
//! verified chunks; it continues by itself once the policy reports the network usable. A large download pauses while
//! the connection is metered (a fixed default, D53). Free disk is checked before starting (size plus
//! `DOWNLOAD_DISK_MARGIN_SHARE`), and when it falls under `DOWNLOAD_PAUSE_FREE_MB` the download pauses (PLT-23) and
//! resumes when space returns. Pause, resume, cancel and a bandwidth cap are supported. Nothing already installed is
//! touched until the new item verifies, and learning never waits on a download (the manager runs off the UI thread).
//!
//! The HTTP transport is behind [`Transport`], so this module holds no HTTP or TLS client and is tested headless.

use crate::generated::keys;
use crate::net::{self, Limits as NetLimits, NoticeState, RefusalReason, Request, ResolvedPolicy};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

const JOURNAL: &str = "journal.json";
const READY: &str = "ready";
const PART: &str = ".part";
const MB: u64 = 1024 * 1024;

/// One file of an item, as the signed manifest lists it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileSpec {
    pub name: String,
    pub url: String,
    pub size_bytes: u64,
    pub sha256: String,
    pub chunk_sha256: Vec<String>,
    pub chunk_bytes: u64,
}

impl FileSpec {
    fn chunks(&self) -> usize {
        self.size_bytes.div_ceil(self.chunk_bytes.max(1)) as usize
    }

    fn range(&self, chunk: usize) -> (u64, u64) {
        let start = chunk as u64 * self.chunk_bytes;
        (start, (self.size_bytes - start).min(self.chunk_bytes))
    }
}

fn safe_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 120
        && name != "."
        && name != ".."
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
}

fn safe_files(job: &Job) -> bool {
    safe_name(&job.download_id)
        && !job.files.is_empty()
        && job.files.len() <= 16
        && job
            .files
            .iter()
            .all(|f| safe_name(&f.name) && f.chunk_bytes > 0)
        && job
            .files
            .iter()
            .map(|f| &f.name)
            .collect::<BTreeSet<_>>()
            .len()
            == job.files.len()
}

/// What the core asks for (`control.download`): an id, the item, its files and the folder to install them into.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Job {
    pub download_id: String,
    pub item_id: String,
    pub files: Vec<FileSpec>,
    pub target: PathBuf,
}

/// Why a download is paused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PauseReason {
    User,
    Metered,
    LowDisk,
}

/// Why a download failed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FailReason {
    /// A chunk failed its hash more than the retries allow, or the whole file did not match.
    Corrupt,
    /// Not enough free disk to start (size plus the margin).
    StorageFull,
    /// The policy refused the request for a reason other than the network (the feature switched off, a host off the
    /// allow-list): the code of the refusal.
    Refused(String),
    /// The job itself does not hold together (chunk hashes that do not cover the file).
    BadJob,
    /// The disk could not be written.
    Io,
}

/// FIGURE PLT-11a.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Queued,
    Downloading,
    WaitingForNetwork,
    Paused(PauseReason),
    Verifying,
    Installing,
    Done,
    Failed(FailReason),
    Cancelled,
}

impl State {
    pub fn name(&self) -> &'static str {
        match self {
            State::Queued => "queued",
            State::Downloading => "downloading",
            State::WaitingForNetwork => "waiting_for_network",
            State::Paused(_) => "paused",
            State::Verifying => "verifying",
            State::Installing => "installing",
            State::Done => "done",
            State::Failed(_) => "failed",
            State::Cancelled => "cancelled",
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(self, State::Done | State::Failed(_) | State::Cancelled)
    }

    fn error_code(&self) -> Option<String> {
        match self {
            State::Paused(PauseReason::Metered) => Some("metered".into()),
            State::Paused(PauseReason::LowDisk) => Some("storage_low".into()),
            State::WaitingForNetwork => Some("waiting_for_network".into()),
            State::Failed(FailReason::Corrupt) => Some("model.damaged".into()),
            State::Failed(FailReason::StorageFull) => Some("storage_full".into()),
            State::Failed(FailReason::Refused(code)) => Some(code.clone()),
            State::Failed(FailReason::BadJob) => Some("bad_job".into()),
            State::Failed(FailReason::Io) => Some("io".into()),
            _ => None,
        }
    }
}

/// A failed fetch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FetchError {
    /// The connection dropped, timed out or could not be made: the item waits for the network.
    ConnectionLost,
    /// The server answered with an error status.
    Status(u16),
    Refused(String),
}

/// The HTTP transport: one byte range of one URL. The policy has already allowed the request when this is called.
pub trait Transport {
    fn fetch(&mut self, url: &str, offset: u64, len: u64) -> Result<Vec<u8>, FetchError>;
}

/// Free space where the download is written.
pub trait Disk {
    fn free_bytes(&self, path: &Path) -> u64;
}

/// Limits from the configuration (ARC-28), never literals in the logic.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Limits {
    pub chunk_retries: u32,
    pub disk_margin_share: f64,
    pub pause_free_bytes: u64,
    /// Bytes per second; `None` is no cap.
    pub bandwidth_cap: Option<u64>,
    pub net: NetLimits,
}

impl Limits {
    /// The shipped limits: the generated configuration keys, and the metered threshold the transport passes in.
    pub fn from_keys(net: NetLimits) -> Limits {
        Limits {
            chunk_retries: keys::DOWNLOAD_CHUNK_RETRIES as u32,
            disk_margin_share: keys::DOWNLOAD_DISK_MARGIN_SHARE,
            pause_free_bytes: (keys::DOWNLOAD_PAUSE_FREE_MB * MB as f64) as u64,
            bandwidth_cap: None,
            net,
        }
    }
}

/// The default chunk size for jobs whose manifest does not say (`DOWNLOAD_CHUNK_MB`).
pub fn default_chunk_bytes() -> u64 {
    keys::DOWNLOAD_CHUNK_MB as u64 * MB
}

/// What one [`Download::step`] did.
#[derive(Debug, Clone, PartialEq)]
pub enum Step {
    /// A chunk was fetched and verified; wait this long before the next (the bandwidth cap).
    Progress { wait: Duration },
    /// A chunk failed its hash and will be fetched again.
    Retry,
    /// Nothing to do until something changes (paused, waiting for the network, terminal).
    Idle,
    /// The state changed (verifying, installing, done, failed...).
    Moved,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Journal {
    job: Job,
    verified: BTreeMap<String, BTreeSet<usize>>,
    user_paused: bool,
    cancelled: bool,
}

/// One item being downloaded, with its journal and part files under `<work>/<download_id>/`.
#[derive(Debug)]
pub struct Download {
    folder: PathBuf,
    journal: Journal,
    pub state: State,
    retries: BTreeMap<(String, usize), u32>,
    started_ms: Option<u64>,
    fetched_since_start: u64,
    /// `control.download_state` frames and `egress.notice` events for the core, in order; the owner drains them.
    pub outbox: Vec<Value>,
    /// Egress ledger rows for the requests made (ARC-10).
    pub ledger: Vec<net::LedgerEntry>,
}

fn io_fail(_: io::Error) -> State {
    State::Failed(FailReason::Io)
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

impl Download {
    /// A new download in `work/<download_id>/` (the journal is written at once).
    pub fn create(job: Job, work: &Path) -> io::Result<Download> {
        if !safe_files(&job) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid download paths or files",
            ));
        }
        let folder = work.join(&job.download_id);
        let state = if job
            .files
            .iter()
            .any(|f| f.chunk_bytes == 0 || f.chunk_sha256.len() != f.chunks())
        {
            State::Failed(FailReason::BadJob)
        } else {
            State::Queued
        };
        let mut download = Download {
            folder,
            journal: Journal {
                job,
                verified: BTreeMap::new(),
                user_paused: false,
                cancelled: false,
            },
            state,
            retries: BTreeMap::new(),
            started_ms: None,
            fetched_since_start: 0,
            outbox: vec![],
            ledger: vec![],
        };
        if !matches!(download.state, State::Failed(_)) {
            download.prepare_folder()?; // a job that cannot run writes nothing
        }
        download.announce(None);
        Ok(download)
    }

    /// The item's folder with its journal and the (empty) part files of zero-length files.
    fn prepare_folder(&self) -> io::Result<()> {
        fs::create_dir_all(&self.folder)?;
        for spec in &self.journal.job.files {
            let part = self.folder.join(format!("{}{PART}", spec.name));
            if spec.size_bytes == 0 && !part.exists() {
                File::create(part)?;
            }
        }
        self.save()
    }

    /// Remove the item's part files and journal (PLT-11: a failed item keeps nothing on disk; a retry starts over).
    fn discard(&mut self) {
        self.journal.verified.clear();
        // Anything that cannot be removed now goes at the next start's orphan sweep (`remove_orphans`).
        let _ = fs::remove_dir_all(&self.folder);
    }

    /// The download `download_id` after a restart: the journal, with every chunk it lists checked again against the
    /// part file (a chunk whose bytes changed is fetched again).
    pub fn reopen(work: &Path, download_id: &str) -> io::Result<Download> {
        if !safe_name(download_id) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid download id",
            ));
        }
        let folder = work.join(download_id);
        let mut journal: Journal = serde_json::from_slice(&fs::read(folder.join(JOURNAL))?)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
        if !safe_files(&journal.job) || journal.job.download_id != download_id {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid download journal paths",
            ));
        }
        for spec in &journal.job.files {
            let part = folder.join(format!("{}{PART}", spec.name));
            let ready = folder.join(READY).join(&spec.name);
            // A crash may split the final move between part files and the ready folder.
            if !part.exists() && ready.is_file() {
                fs::rename(ready, &part)?;
            }
            if spec.size_bytes == 0 && !part.exists() {
                File::create(&part)?;
            }
            let listed = journal.verified.entry(spec.name.clone()).or_default();
            let still: BTreeSet<usize> = listed
                .iter()
                .copied()
                .filter(|&chunk| chunk_on_disk_ok(&part, spec, chunk))
                .collect();
            *listed = still;
        }
        let state = if journal.cancelled {
            State::Cancelled
        } else if journal.user_paused {
            State::Paused(PauseReason::User)
        } else {
            State::Queued
        };
        let mut download = Download {
            folder,
            journal,
            state,
            retries: BTreeMap::new(),
            started_ms: None,
            fetched_since_start: 0,
            outbox: vec![],
            ledger: vec![],
        };
        download.announce(None);
        Ok(download)
    }

    pub fn job(&self) -> &Job {
        &self.journal.job
    }

    pub fn bytes_total(&self) -> u64 {
        self.journal.job.files.iter().map(|f| f.size_bytes).sum()
    }

    /// Bytes in verified chunks.
    pub fn bytes_done(&self) -> u64 {
        self.journal
            .job
            .files
            .iter()
            .map(|spec| {
                self.journal
                    .verified
                    .get(&spec.name)
                    .map(|chunks| chunks.iter().map(|&c| spec.range(c).1).sum::<u64>())
                    .unwrap_or(0)
            })
            .sum()
    }

    fn save(&self) -> io::Result<()> {
        let temp = self.folder.join(format!("{JOURNAL}.tmp"));
        let mut file = File::create(&temp)?;
        file.write_all(&serde_json::to_vec(&self.journal).unwrap_or_default())?;
        file.sync_all()?;
        fs::rename(temp, self.folder.join(JOURNAL))
    }

    fn set(&mut self, state: State, eta_s: Option<u64>) {
        if self.state != state {
            if matches!(state, State::Failed(_)) {
                self.discard();
            }
            self.state = state;
            self.announce(eta_s);
        }
    }

    fn announce(&mut self, eta_s: Option<u64>) {
        self.outbox.push(json!({
            "type": "control.download_state",
            "download_id": self.journal.job.download_id,
            "state": self.state.name(),
            "bytes_done": self.bytes_done(),
            "bytes_total": self.bytes_total(),
            "eta_s": eta_s,
            "error_code": self.state.error_code(),
        }));
    }

    /// The user's (or the adult's) pause.
    pub fn pause(&mut self) -> io::Result<()> {
        if !self.state.is_terminal() {
            self.journal.user_paused = true;
            self.save()?;
            self.set(State::Paused(PauseReason::User), None);
        }
        Ok(())
    }

    pub fn resume(&mut self) -> io::Result<()> {
        let retry = matches!(self.state, State::Failed(ref why) if *why != FailReason::BadJob);
        if self.state == State::Paused(PauseReason::User) || retry {
            self.journal.user_paused = false;
            self.retries.clear();
            self.prepare_folder()?;
            self.set(State::Queued, None);
        }
        Ok(())
    }

    /// Cancel: the part files and journal go; nothing is installed.
    pub fn cancel(&mut self) -> io::Result<()> {
        if self.state != State::Done {
            self.journal.cancelled = true;
            self.set(State::Cancelled, None);
            fs::remove_dir_all(&self.folder).or_else(|e| {
                if e.kind() == io::ErrorKind::NotFound {
                    Ok(())
                } else {
                    Err(e)
                }
            })?;
        }
        Ok(())
    }

    fn next_chunk(&self) -> Option<(usize, usize)> {
        for (index, spec) in self.journal.job.files.iter().enumerate() {
            let done = self.journal.verified.get(&spec.name);
            for chunk in 0..spec.chunks() {
                if !done.is_some_and(|d| d.contains(&chunk)) {
                    return Some((index, chunk));
                }
            }
        }
        None
    }

    fn remaining_bytes(&self) -> u64 {
        self.bytes_total() - self.bytes_done()
    }

    /// Do one unit of work: start, fetch and verify one chunk, or verify and install the whole item.
    pub fn step(
        &mut self,
        policy: &ResolvedPolicy,
        limits: &Limits,
        transport: &mut dyn Transport,
        disk: &dyn Disk,
        now_ms: u64,
    ) -> Step {
        match self.state {
            State::Done
            | State::Failed(_)
            | State::Cancelled
            | State::Paused(PauseReason::User)
            | State::Verifying
            | State::Installing => {
                if matches!(self.state, State::Verifying | State::Installing) {
                    return self.finish();
                }
                return Step::Idle;
            }
            _ => {}
        }
        let free = disk.free_bytes(&self.folder);
        if self.state == State::Queued && self.started_ms.is_none() {
            let needed = (self.remaining_bytes() as f64 * (1.0 + limits.disk_margin_share)) as u64;
            if free < needed {
                self.set(State::Failed(FailReason::StorageFull), None);
                return Step::Moved;
            }
        }
        if free < limits.pause_free_bytes {
            self.set(State::Paused(PauseReason::LowDisk), None);
            return Step::Idle;
        }
        let Some((index, chunk)) = self.next_chunk() else {
            self.set(State::Verifying, None);
            return Step::Moved;
        };
        let spec = self.journal.job.files[index].clone();
        let request = Request {
            feature: "downloads".into(),
            method: "GET".into(),
            url: spec.url.clone(),
            payload_class: "download_request".into(),
            body_len: 0,
            carries_credential: false,
            download_len: Some(self.bytes_total()),
        };
        let allowed = match net::check(policy, &request, &limits.net) {
            Ok(allowed) => allowed,
            Err(refusal) => {
                if let Some(notice) = refusal.blocked_notice(policy) {
                    self.outbox.push(notice);
                }
                let state = match refusal.reason {
                    RefusalReason::NetworkUnavailable => State::WaitingForNetwork,
                    RefusalReason::MeteredLargeDownload => State::Paused(PauseReason::Metered),
                    other => State::Failed(FailReason::Refused(other.code().into())),
                };
                self.set(state, None);
                return Step::Idle;
            }
        };
        if self.started_ms.is_none() {
            self.started_ms = Some(now_ms);
        }
        self.set(State::Downloading, None);
        let (offset, len) = spec.range(chunk);
        self.ledger.push(allowed.ledger_entry(now_ms));
        self.outbox.push(allowed.notice(NoticeState::Started));
        let fetched = transport.fetch(&spec.url, offset, len);
        self.outbox.push(allowed.notice(NoticeState::Ended));
        let bytes = match fetched {
            Ok(bytes) => bytes,
            Err(FetchError::ConnectionLost) => {
                self.set(State::WaitingForNetwork, None);
                return Step::Idle;
            }
            Err(FetchError::Status(_)) => return self.chunk_failed(&spec.name, chunk, limits),
            Err(FetchError::Refused(code)) => {
                self.set(State::Failed(FailReason::Refused(code)), None);
                return Step::Moved;
            }
        };
        if bytes.len() as u64 != len || sha256_hex(&bytes) != spec.chunk_sha256[chunk] {
            return self.chunk_failed(&spec.name, chunk, limits);
        }
        let part = self.folder.join(format!("{}{PART}", spec.name));
        if let Err(error) = write_at(&part, offset, &bytes) {
            self.set(io_fail(error), None);
            return Step::Moved;
        }
        self.journal
            .verified
            .entry(spec.name.clone())
            .or_default()
            .insert(chunk);
        if let Err(error) = self.save() {
            self.set(io_fail(error), None);
            return Step::Moved;
        }
        self.fetched_since_start += len;
        let eta = self.eta_s(now_ms);
        self.announce(eta);
        let wait = limits
            .bandwidth_cap
            .filter(|cap| *cap > 0)
            .map(|cap| Duration::from_secs_f64(len as f64 / cap as f64))
            .unwrap_or_default();
        Step::Progress { wait }
    }

    fn eta_s(&self, now_ms: u64) -> Option<u64> {
        let started = self.started_ms?;
        let elapsed_ms = now_ms.saturating_sub(started);
        if elapsed_ms == 0 || self.fetched_since_start == 0 {
            return None;
        }
        let rate = self.fetched_since_start as f64 / elapsed_ms as f64; // bytes per ms
        Some((self.remaining_bytes() as f64 / rate / 1000.0).ceil() as u64)
    }

    fn chunk_failed(&mut self, name: &str, chunk: usize, limits: &Limits) -> Step {
        let count = self.retries.entry((name.to_string(), chunk)).or_insert(0);
        *count += 1;
        if *count > limits.chunk_retries {
            self.set(State::Failed(FailReason::Corrupt), None);
            return Step::Moved;
        }
        Step::Retry
    }

    /// Verify every whole file, then install them by one atomic rename of their folder onto the target.
    fn finish(&mut self) -> Step {
        if self.state == State::Verifying {
            for spec in self.journal.job.files.clone() {
                let part = self.folder.join(format!("{}{PART}", spec.name));
                match file_sha256(&part) {
                    Ok(sha) if sha == spec.sha256 => {}
                    Ok(_) | Err(_) => {
                        self.journal.verified.remove(&spec.name);
                        let _ = self.save();
                        self.set(State::Failed(FailReason::Corrupt), None);
                        return Step::Moved;
                    }
                }
            }
            self.set(State::Installing, None);
            return Step::Moved;
        }
        match self.install() {
            Ok(()) => {
                self.set(State::Done, Some(0));
                let _ = fs::remove_dir_all(&self.folder);
            }
            Err(error) => self.set(io_fail(error), None),
        }
        Step::Moved
    }

    fn install(&self) -> io::Result<()> {
        let ready = self.folder.join(READY);
        if ready.exists() {
            fs::remove_dir_all(&ready)?;
        }
        fs::create_dir_all(&ready)?;
        for spec in &self.journal.job.files {
            let part = self.folder.join(format!("{}{PART}", spec.name));
            File::open(&part)?.sync_all()?;
            fs::rename(part, ready.join(&spec.name))?;
        }
        let target = &self.journal.job.target;
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        if target.exists() {
            fs::remove_dir_all(target)?;
        }
        fs::rename(ready, target)
    }

    /// Run steps until the item is terminal, paused or waiting (a test and batch helper; the app's thread calls
    /// [`Download::step`] itself so it can sleep for the bandwidth cap and react to pause and cancel).
    pub fn run(
        &mut self,
        policy: &ResolvedPolicy,
        limits: &Limits,
        transport: &mut dyn Transport,
        disk: &dyn Disk,
        mut now_ms: impl FnMut() -> u64,
    ) -> State {
        loop {
            match self.step(policy, limits, transport, disk, now_ms()) {
                Step::Idle => return self.state.clone(),
                Step::Moved if self.state.is_terminal() => return self.state.clone(),
                _ => {}
            }
        }
    }
}

/// Remove every download folder under `work` that is not one of `keep`: what a crash in the middle of a failure or a
/// cancel, or a download the core no longer tracks, left behind (PLT-11). Returns the ids removed. Call it before any
/// download of this run starts.
pub fn remove_orphans(work: &Path, keep: &BTreeSet<String>) -> Vec<String> {
    let Ok(entries) = fs::read_dir(work) else {
        return vec![];
    };
    let mut removed = vec![];
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let is_dir = entry.file_type().is_ok_and(|t| t.is_dir());
        if is_dir
            && safe_name(&name)
            && !keep.contains(&name)
            && fs::remove_dir_all(entry.path()).is_ok()
        {
            removed.push(name);
        }
    }
    removed.sort();
    removed
}

fn write_at(path: &Path, offset: u64, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(path)?;
    file.seek(SeekFrom::Start(offset))?;
    file.write_all(bytes)?;
    file.sync_data()
}

fn chunk_on_disk_ok(part: &Path, spec: &FileSpec, chunk: usize) -> bool {
    let (offset, len) = spec.range(chunk);
    let Ok(mut file) = File::open(part) else {
        return false;
    };
    let mut buffer = vec![0u8; len as usize];
    if file.seek(SeekFrom::Start(offset)).is_err() || file.read_exact(&mut buffer).is_err() {
        return false;
    }
    spec.chunk_sha256.get(chunk) == Some(&sha256_hex(&buffer))
}

fn file_sha256(path: &Path) -> io::Result<String> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; MB as usize];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::net::Limits as NetLimits;

    const HOST: &str = "downloads.dev.jana.invalid";

    fn policy(network: &str, downloads: bool) -> ResolvedPolicy {
        ResolvedPolicy::from_json(
            &json!({
                "version": 1, "environment": "dev", "release": false, "network": network,
                "features": {
                    "downloads": {"enabled": downloads, "hosts": [HOST], "payload_classes": ["download_request"],
                                  "authenticated": false, "destination_label": "Downloads", "data_classes": []},
                },
                "pins": {},
            })
            .to_string(),
        )
        .unwrap()
    }

    fn limits() -> Limits {
        Limits {
            chunk_retries: 3,
            disk_margin_share: 0.1,
            pause_free_bytes: 500,
            bandwidth_cap: None,
            net: NetLimits {
                metered_large_download_bytes: 1_000_000,
            },
        }
    }

    /// A stand-in server: the bytes of each URL, a log of every range fetched, and switches to drop the connection
    /// or corrupt a chunk.
    struct Server {
        files: BTreeMap<String, Vec<u8>>,
        fetched: Vec<(String, u64)>,
        drop_after: Option<usize>,
        corrupt: BTreeMap<u64, u32>, // offset -> how many more times to corrupt it
    }

    impl Transport for Server {
        fn fetch(&mut self, url: &str, offset: u64, len: u64) -> Result<Vec<u8>, FetchError> {
            if self.drop_after == Some(0) {
                return Err(FetchError::ConnectionLost);
            }
            if let Some(left) = self.drop_after.as_mut() {
                *left -= 1;
            }
            self.fetched.push((url.to_string(), offset));
            let body = &self.files[url];
            let mut chunk = body[offset as usize..(offset + len) as usize].to_vec();
            if let Some(times) = self.corrupt.get_mut(&offset)
                && *times > 0
            {
                *times -= 1;
                chunk[0] ^= 0xff;
            }
            Ok(chunk)
        }
    }

    struct Free(u64);

    impl Disk for Free {
        fn free_bytes(&self, _: &Path) -> u64 {
            self.0
        }
    }

    fn content(len: usize, seed: u8) -> Vec<u8> {
        (0..len)
            .map(|i| (i as u8).wrapping_mul(31).wrapping_add(seed))
            .collect()
    }

    fn spec(name: &str, body: &[u8], chunk: u64) -> FileSpec {
        FileSpec {
            name: name.into(),
            url: format!("https://{HOST}/models/{name}"),
            size_bytes: body.len() as u64,
            sha256: sha256_hex(body),
            chunk_sha256: body.chunks(chunk as usize).map(sha256_hex).collect(),
            chunk_bytes: chunk,
        }
    }

    fn setup(dir: &Path) -> (Job, Server) {
        let weights = content(10 * 64 + 17, 7);
        let projector = content(3 * 64, 3);
        let files = vec![
            spec("model.gguf", &weights, 64),
            spec("mmproj.gguf", &projector, 64),
        ];
        let server = Server {
            files: files
                .iter()
                .zip([weights, projector])
                .map(|(f, b)| (f.url.clone(), b))
                .collect(),
            fetched: vec![],
            drop_after: None,
            corrupt: BTreeMap::new(),
        };
        let job = Job {
            download_id: "dl_01JTESTDOWNLOAD00000000000".into(),
            item_id: "mp.synth.8b.q4_k_m.low".into(),
            files,
            target: dir.join("models/incoming/mp.synth.8b.q4_k_m.low"),
        };
        (job, server)
    }

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("jana-dl-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn clock() -> impl FnMut() -> u64 {
        let mut t = 0;
        move || {
            t += 100;
            t
        }
    }

    /// PLT-11: cutting the network at 50% and restoring it after an app restart resumes from the last verified chunk
    /// without fetching a verified chunk again.
    #[test]
    fn plt11_resume_across_restart() {
        let dir = temp("restart");
        let (job, mut server) = setup(&dir);
        let work = dir.join("downloads");
        let chunks: usize = job.files.iter().map(|f| f.chunks()).sum();
        server.drop_after = Some(chunks / 2);
        let mut first = Download::create(job.clone(), &work).unwrap();
        let state = first.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::WaitingForNetwork);
        let verified_before = first.bytes_done();
        assert!(verified_before > 0 && verified_before < first.bytes_total());
        drop(first); // the app quits

        let fetched_before: Vec<(String, u64)> = server.fetched.clone();
        server.drop_after = None;
        let mut again = Download::reopen(&work, &job.download_id).unwrap();
        assert_eq!(
            again.bytes_done(),
            verified_before,
            "the journal kept every verified chunk"
        );
        let state = again.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Done);
        let refetched: Vec<_> = server.fetched[fetched_before.len()..]
            .iter()
            .filter(|f| fetched_before.contains(f))
            .collect();
        assert!(
            refetched.is_empty(),
            "no verified chunk was fetched again: {refetched:?}"
        );
        assert_eq!(
            server.fetched.len(),
            chunks,
            "every chunk was fetched exactly once"
        );
        for spec in &job.files {
            assert_eq!(
                file_sha256(&job.target.join(&spec.name)).unwrap(),
                spec.sha256
            );
        }
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn restart_during_final_folder_move_keeps_verified_files() {
        let dir = temp("final-move");
        let (job, mut server) = setup(&dir);
        let work = dir.join("downloads");
        let mut first = Download::create(job.clone(), &work).unwrap();
        while first.state != State::Installing {
            first.step(
                &policy("online", true),
                &limits(),
                &mut server,
                &Free(1 << 30),
                100,
            );
        }
        let fetched = server.fetched.len();
        let ready = first.folder.join(READY);
        fs::create_dir(&ready).unwrap();
        fs::rename(
            first.folder.join(format!("{}{PART}", job.files[0].name)),
            ready.join(&job.files[0].name),
        )
        .unwrap();
        drop(first); // power goes between two file renames
        let mut again = Download::reopen(&work, &job.download_id).unwrap();
        assert_eq!(again.bytes_done(), again.bytes_total());
        assert_eq!(
            again.run(
                &policy("online", true),
                &limits(),
                &mut server,
                &Free(1 << 30),
                clock()
            ),
            State::Done
        );
        assert_eq!(server.fetched.len(), fetched);
        for file in job.files {
            assert_eq!(
                file_sha256(&job.target.join(file.name)).unwrap(),
                file.sha256
            );
        }
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn rejects_path_traversal_and_duplicate_names_before_writing() {
        let dir = temp("bad-paths");
        let (job, _) = setup(&dir);
        for name in ["../outside", "/absolute", ".."] {
            let mut bad = job.clone();
            bad.files[0].name = name.into();
            assert!(Download::create(bad, &dir.join("work")).is_err());
        }
        let mut duplicate = job.clone();
        duplicate.files.push(job.files[0].clone());
        assert!(Download::create(duplicate, &dir.join("work")).is_err());
        let mut bad_id = job;
        bad_id.download_id = "../outside".into();
        assert!(Download::create(bad_id, &dir.join("work")).is_err());
        assert!(!dir.join("work").exists());
        let _ = fs::remove_dir_all(dir);
    }

    /// UXS-11: an interrupted download resumes from its last byte (the end of its last verified chunk) after the
    /// connection returns, and goes through `waiting_for_network` on the way.
    #[test]
    fn uxs11_resume_download() {
        let dir = temp("uxs11");
        let (job, mut server) = setup(&dir);
        server.drop_after = Some(4);
        let mut download = Download::create(job.clone(), &dir.join("w")).unwrap();
        let state = download.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::WaitingForNetwork);
        let resumed_from = download.bytes_done();
        assert_eq!(resumed_from, 4 * 64);
        server.drop_after = None;
        let fetched = server.fetched.len();
        let state = download.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Done);
        assert_eq!(
            server.fetched[fetched].1, resumed_from,
            "the next range starts at the last verified byte"
        );
        let states: Vec<&str> = download
            .outbox
            .iter()
            .filter_map(|e| e["state"].as_str())
            .collect();
        assert!(
            states.contains(&"waiting_for_network") && states.ends_with(&["installing", "done"])
        );
        let _ = fs::remove_dir_all(dir);
    }

    /// API-29: while offline the download waits; when the connectivity layer reports `online` it continues from its
    /// last verified chunk.
    #[test]
    fn api29_download_resume() {
        let dir = temp("api29");
        let (job, mut server) = setup(&dir);
        let mut download = Download::create(job.clone(), &dir.join("w")).unwrap();
        let mut steps = 0;
        while steps < 3 {
            download.step(
                &policy("online", true),
                &limits(),
                &mut server,
                &Free(1 << 30),
                0,
            );
            steps += 1;
        }
        let done = download.bytes_done();
        assert_eq!(
            download.run(
                &policy("offline", true),
                &limits(),
                &mut server,
                &Free(1 << 30),
                clock()
            ),
            State::WaitingForNetwork
        );
        assert_eq!(download.bytes_done(), done, "nothing is lost while offline");
        let fetched = server.fetched.len();
        assert_eq!(
            download.run(
                &policy("online", true),
                &limits(),
                &mut server,
                &Free(1 << 30),
                clock()
            ),
            State::Done
        );
        assert_eq!(server.fetched[fetched].1, done);
        let ledger = download.ledger.len();
        assert_eq!(
            ledger,
            server.fetched.len(),
            "every request is in the egress ledger"
        );
        let _ = fs::remove_dir_all(dir);
    }

    /// PLT-11: a corrupted chunk is fetched again; after three failures the item is `failed` with nothing installed.
    #[test]
    fn plt11_chunk_corruption_retry_then_fail() {
        let dir = temp("corrupt");
        let (job, mut server) = setup(&dir);
        server.corrupt.insert(128, 2); // twice wrong, then right: the download completes
        let mut download = Download::create(job.clone(), &dir.join("w")).unwrap();
        let state = download.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Done);
        let at_128: Vec<&String> = server
            .fetched
            .iter()
            .filter(|f| f.1 == 128)
            .map(|f| &f.0)
            .collect();
        assert_eq!(
            at_128.len(),
            4,
            "three tries for the weights' chunk at 128, one for the projector's"
        );

        let other = temp("corrupt2");
        let (mut job2, mut server2) = setup(&other);
        job2.download_id = "dl_01JTESTDOWNLOAD00000000001".into();
        server2.corrupt.insert(192, 10);
        let mut failing = Download::create(job2.clone(), &other.join("w")).unwrap();
        let state = failing.run(
            &policy("online", true),
            &limits(),
            &mut server2,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Failed(FailReason::Corrupt));
        assert_eq!(
            server2.fetched.iter().filter(|f| f.1 == 192).count(),
            4,
            "one try and three retries"
        );
        assert!(!job2.target.exists(), "nothing is installed");
        assert!(
            !other.join("w").join(&job2.download_id).exists(),
            "no part file outlives the failure"
        );
        assert_eq!(
            failing.outbox.last().unwrap()["error_code"],
            "model.damaged"
        );
        let _ = fs::remove_dir_all(dir);
        let _ = fs::remove_dir_all(other);
    }

    /// PLT-23 (shell half): when free disk falls under the floor the download pauses with nothing lost, and resumes
    /// when space returns; a download that cannot fit (size plus margin) never starts.
    #[test]
    fn plt23_low_disk_behaviour() {
        let dir = temp("disk");
        let (job, mut server) = setup(&dir);
        let mut download = Download::create(job.clone(), &dir.join("w")).unwrap();
        download.step(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            0,
        );
        let done = download.bytes_done();
        let state = download.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(400),
            clock(),
        );
        assert_eq!(state, State::Paused(PauseReason::LowDisk));
        assert_eq!(download.bytes_done(), done);
        assert_eq!(download.outbox.last().unwrap()["error_code"], "storage_low");
        let state = download.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Done);

        let small = temp("disk2");
        let (mut big, _) = setup(&small);
        big.download_id = "dl_01JTESTDOWNLOAD00000000002".into();
        let total: u64 = big.files.iter().map(|f| f.size_bytes).sum();
        let mut refused = Download::create(big, &small.join("w")).unwrap();
        let state = refused.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(total),
            clock(),
        );
        assert_eq!(
            state,
            State::Failed(FailReason::StorageFull),
            "size plus the margin must be free"
        );
        let _ = fs::remove_dir_all(dir);
        let _ = fs::remove_dir_all(small);
    }

    #[test]
    fn metered_pause_user_pause_cancel_and_cap() {
        let dir = temp("controls");
        let (job, mut server) = setup(&dir);
        let mut download = Download::create(job.clone(), &dir.join("w")).unwrap();
        let mut tight = limits();
        tight.net.metered_large_download_bytes = 10;
        let state = download.run(
            &policy("metered", true),
            &tight,
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Paused(PauseReason::Metered));
        assert!(
            server.fetched.is_empty(),
            "nothing is fetched on a metered connection"
        );
        let state = download.run(
            &policy("online", false),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(
            state,
            State::Failed(FailReason::Refused("feature_off".into()))
        );
        assert!(
            download.outbox.iter().any(|e| e["state"] == "blocked"),
            "a blocked notice"
        );
        download.resume().unwrap();
        download.pause().unwrap();
        assert_eq!(
            download.run(
                &policy("online", true),
                &limits(),
                &mut server,
                &Free(1 << 30),
                clock()
            ),
            State::Paused(PauseReason::User)
        );
        download.resume().unwrap();
        let mut capped = limits();
        capped.bandwidth_cap = Some(640);
        match download.step(
            &policy("online", true),
            &capped,
            &mut server,
            &Free(1 << 30),
            0,
        ) {
            Step::Progress { wait } => assert_eq!(wait, Duration::from_millis(100)),
            other => panic!("expected progress, got {other:?}"),
        }
        download.cancel().unwrap();
        assert_eq!(download.state, State::Cancelled);
        assert!(!dir.join("w").join(&job.download_id).exists() && !job.target.exists());
        let _ = fs::remove_dir_all(dir);
    }

    /// PLT-11: a failed download keeps no part files (a retry starts over and still completes), a job that cannot
    /// run writes nothing, and at start the folders of downloads nobody tracks any more are removed.
    #[test]
    fn test_plt11_failed_and_orphaned_downloads_leave_no_part_files() {
        let dir = temp("leftovers");
        let work = dir.join("w");
        let (job, mut server) = setup(&dir);
        let mut download = Download::create(job.clone(), &work).unwrap();
        download.step(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            0,
        );
        assert!(download.bytes_done() > 0);
        let state = download.run(
            &policy("online", false),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert!(matches!(state, State::Failed(_)));
        assert!(
            !work.join(&job.download_id).exists(),
            "failed: nothing kept"
        );
        download.resume().unwrap();
        let state = download.run(
            &policy("online", true),
            &limits(),
            &mut server,
            &Free(1 << 30),
            clock(),
        );
        assert_eq!(state, State::Done, "a retry after a failure starts over");

        let (mut bad, _) = setup(&dir);
        bad.download_id = "dl_01JTESTDOWNLOAD00000000003".into();
        bad.files[0].chunk_sha256.pop();
        let mut refused = Download::create(bad.clone(), &work).unwrap();
        assert_eq!(refused.state, State::Failed(FailReason::BadJob));
        assert!(!work.join(&bad.download_id).exists());
        refused.resume().unwrap();
        assert_eq!(
            refused.state,
            State::Failed(FailReason::BadJob),
            "never run"
        );

        // Orphans: one the core still tracks stays; one it does not, and any stray, go.
        for id in [
            "dl_01JTESTDOWNLOAD00000000004",
            "dl_01JTESTDOWNLOAD00000000005",
        ] {
            let (mut other, _) = setup(&dir);
            other.download_id = id.into();
            Download::create(other, &work).unwrap();
        }
        fs::write(work.join("note.txt"), b"not a download").unwrap();
        let keep = BTreeSet::from(["dl_01JTESTDOWNLOAD00000000004".to_string()]);
        assert_eq!(
            remove_orphans(&work, &keep),
            ["dl_01JTESTDOWNLOAD00000000005"]
        );
        assert!(
            work.join("dl_01JTESTDOWNLOAD00000000004/journal.json")
                .is_file()
        );
        assert!(
            work.join("note.txt").is_file(),
            "only download folders are touched"
        );
        assert!(remove_orphans(&dir.join("missing"), &keep).is_empty());
        let _ = fs::remove_dir_all(dir);
    }
}
