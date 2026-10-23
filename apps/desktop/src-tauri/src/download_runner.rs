//! Control-channel downloads run off the webview thread; policy refresh and controls interrupt in-flight HTTP.
use crate::control::{
    Download as DownloadFrame, DownloadControl, DownloadControlAction, DownloadItemKind,
    DownloadLimits, DownloadState as DownloadProgress, DownloadStateState, EgressLedger,
    EgressNotice, ToCore, ToShell,
};
use crate::download_http::{self, Https, Policy};
use crate::downloads::{self, Disk, Download, FileSpec, Job, Step, Transport};
use crate::generated::keys;
use crate::net::{Environment, FeaturePolicy, Network, NoticeState, ResolvedPolicy};
use crate::supervisor::Supervisor;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, RwLock, mpsc};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const POLICY_TABLE: &str =
    include_str!("../../../../services/agent-core/agent_core/net/policy.json");

pub struct Runner {
    stop: Arc<AtomicBool>,
    threads: Mutex<Vec<JoinHandle<()>>>,
}

struct Handle {
    job: Job,
    control: mpsc::Sender<(DownloadControlAction, Option<DownloadLimits>)>,
    interrupted: Arc<AtomicBool>,
    last: Arc<Mutex<DownloadProgress>>,
}

impl Runner {
    pub fn start(core: Arc<Supervisor>, data: PathBuf, release: bool) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let policy: Policy = Arc::new(RwLock::new(ResolvedPolicy::all_off()));
        let loaded = Arc::new(AtomicBool::new(false));
        let monitor = {
            let (core, stop, policy, loaded) =
                (core.clone(), stop.clone(), policy.clone(), loaded.clone());
            thread::spawn(move || monitor(&core, &stop, &policy, &loaded, release))
        };
        let dispatch = {
            let stop = stop.clone();
            thread::spawn(move || {
                // Before any job of this run starts: the part files of downloads the core no longer tracks go.
                if let Some(keep) = tracked_downloads(&data) {
                    downloads::remove_orphans(&data.join("models/download-cache"), &keep);
                }
                let mut jobs: BTreeMap<String, Handle> = BTreeMap::new();
                let mut workers = Vec::new();
                while !stop.load(Ordering::SeqCst) {
                    for frame in core.take_downloads() {
                        match frame {
                            ToShell::Download(DownloadFrame {
                                download_id,
                                item,
                                files,
                                target,
                            }) => {
                                let job = Job {
                                    download_id: download_id.clone(),
                                    item_id: item.id.clone(),
                                    files: files
                                        .into_iter()
                                        .map(|f| FileSpec {
                                            name: f.name,
                                            url: f.url,
                                            size_bytes: f.size_bytes,
                                            sha256: f.sha256,
                                            chunk_sha256: f.chunk_sha256,
                                            chunk_bytes: f
                                                .chunk_bytes
                                                .unwrap_or_else(downloads::default_chunk_bytes),
                                        })
                                        .collect(),
                                    target: target.into(),
                                };
                                if item.kind != DownloadItemKind::ModelPack
                                    || !valid_job(&job, &data)
                                {
                                    core.send(&ToCore::DownloadState(failed(
                                        &download_id,
                                        "bad_job",
                                    )));
                                    continue;
                                }
                                if let Some(handle) = jobs.get(&download_id) {
                                    let progress = if handle.job == job {
                                        handle
                                            .last
                                            .lock()
                                            .unwrap_or_else(|p| p.into_inner())
                                            .clone()
                                    } else {
                                        failed(&download_id, "bad_job")
                                    };
                                    core.send(&ToCore::DownloadState(progress));
                                    continue;
                                }
                                let (control, rx) = mpsc::channel();
                                let interrupted = Arc::new(AtomicBool::new(false));
                                let last = Arc::new(Mutex::new(DownloadProgress {
                                    download_id: download_id.clone(),
                                    state: DownloadStateState::Queued,
                                    bytes_done: 0,
                                    bytes_total: job.files.iter().map(|f| f.size_bytes).sum(),
                                    eta_s: None,
                                    error_code: None,
                                }));
                                let (
                                    core,
                                    policy,
                                    stop,
                                    loaded,
                                    last_worker,
                                    interrupt_worker,
                                    job_worker,
                                    data,
                                ) = (
                                    core.clone(),
                                    policy.clone(),
                                    stop.clone(),
                                    loaded.clone(),
                                    last.clone(),
                                    interrupted.clone(),
                                    job.clone(),
                                    data.clone(),
                                );
                                workers.push(thread::spawn(move || {
                                    work(
                                        &core,
                                        job_worker,
                                        &data,
                                        policy,
                                        &stop,
                                        &loaded,
                                        interrupt_worker,
                                        rx,
                                        last_worker,
                                    )
                                }));
                                jobs.insert(
                                    download_id,
                                    Handle {
                                        job,
                                        control,
                                        interrupted,
                                        last,
                                    },
                                );
                            }
                            ToShell::DownloadControl(DownloadControl {
                                download_id,
                                action,
                                limits,
                            }) => {
                                if let Some(handle) = jobs.get(&download_id) {
                                    if action != DownloadControlAction::Resume {
                                        handle.interrupted.store(true, Ordering::SeqCst);
                                    }
                                    if handle.control.send((action, limits)).is_err()
                                        && action == DownloadControlAction::Cancel
                                    {
                                        let cache = data.join("models/download-cache");
                                        if let Ok(mut download) =
                                            Download::reopen(&cache, &download_id)
                                        {
                                            let _ = download.cancel();
                                        }
                                    }
                                }
                            }
                            _ => {}
                        }
                    }
                    thread::sleep(poll());
                }
                let deadline = Instant::now() + Duration::from_secs_f64(keys::SHUTDOWN_GRACE_S);
                for worker in workers {
                    while !worker.is_finished() && Instant::now() < deadline {
                        thread::sleep(poll());
                    }
                    if worker.is_finished() {
                        let _ = worker.join();
                    }
                }
            })
        };
        Self {
            stop,
            threads: Mutex::new(vec![monitor, dispatch]),
        }
    }

    pub fn shutdown(&self) {
        self.stop.store(true, Ordering::SeqCst);
        let deadline = Instant::now() + Duration::from_secs_f64(keys::SHUTDOWN_GRACE_S);
        for worker in std::mem::take(&mut *self.threads.lock().unwrap_or_else(|p| p.into_inner())) {
            while !worker.is_finished() && Instant::now() < deadline {
                thread::sleep(poll());
            }
            if worker.is_finished() {
                let _ = worker.join();
            }
        }
    }
}

impl Drop for Runner {
    fn drop(&mut self) {
        self.shutdown();
    }
}

fn poll() -> Duration {
    Duration::from_millis(keys::DOWNLOAD_CONTROL_POLL_MS as u64)
}
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
fn failed(id: &str, code: &str) -> DownloadProgress {
    DownloadProgress {
        download_id: id.into(),
        state: DownloadStateState::Failed,
        bytes_done: 0,
        bytes_total: 0,
        eta_s: None,
        error_code: Some(code.into()),
    }
}

/// The downloads the core still means to finish (its `models/downloads.json` records that are not done, failed or
/// cancelled): their part files are kept across a restart. `None` when the record exists but cannot be read, so
/// nothing is removed on a guess.
fn tracked_downloads(data: &Path) -> Option<BTreeSet<String>> {
    let bytes = match std::fs::read(data.join("models/downloads.json")) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Some(BTreeSet::new());
        }
        Err(_) => return None,
    };
    let records: BTreeMap<String, Value> = serde_json::from_slice(&bytes).ok()?;
    Some(
        records
            .into_iter()
            .filter(|(_, r)| !matches!(r["state"].as_str(), Some("done" | "failed" | "cancelled")))
            .map(|(id, _)| id)
            .collect(),
    )
}

fn valid_job(job: &Job, data: &Path) -> bool {
    let identifier = |name: &str| {
        !name.is_empty()
            && name.len() <= 120
            && name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            && name != "."
            && name != ".."
    };
    let hash = |s: &str| {
        s.len() == 64
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    };
    job.download_id.starts_with("dl_")
        && identifier(&job.download_id)
        && identifier(&job.item_id)
        && job.target == data.join("models").join("incoming").join(&job.item_id)
        && !job.files.is_empty()
        && job.files.len() <= 16
        && job
            .files
            .iter()
            .try_fold(0u64, |total, f| total.checked_add(f.size_bytes))
            .is_some()
        && job.files.iter().all(|f| {
            identifier(&f.name)
                && hash(&f.sha256)
                && f.chunk_bytes > 0
                && f.chunk_bytes <= downloads::default_chunk_bytes()
                && f.chunk_sha256.len() as u64 == f.size_bytes.div_ceil(f.chunk_bytes)
                && f.chunk_sha256.iter().all(|s| hash(s))
        })
}

fn resolved(state: &Value, release: bool) -> Result<ResolvedPolicy, String> {
    let table: Value = serde_json::from_str(POLICY_TABLE).map_err(|e| e.to_string())?;
    let env = if release { "production" } else { "dev" };
    let network: Network =
        serde_json::from_value(state["network"].clone()).map_err(|e| e.to_string())?;
    let mut features = BTreeMap::new();
    let mut pins = BTreeMap::new();
    let rows = state["features"]
        .as_object()
        .ok_or("missing connectivity features")?;
    for (name, flag) in rows {
        if !matches!(name.as_str(), "downloads" | "update_checks") {
            continue;
        }
        let row = &table["features"][name];
        let service = row["service"].as_str().ok_or("unknown service")?;
        let host = table["services"][env][service]
            .as_str()
            .ok_or("unknown host")?
            .to_string();
        pins.insert(
            host.clone(),
            serde_json::from_value(table["pins"][env].clone()).map_err(|e| e.to_string())?,
        );
        features.insert(
            name.clone(),
            FeaturePolicy {
                enabled: flag["enabled"].as_bool().ok_or("missing switch")?,
                hosts: vec![host],
                payload_classes: serde_json::from_value(row["payload_classes"].clone())
                    .map_err(|e| e.to_string())?,
                authenticated: false,
                destination_label: row["destination_label"]
                    .as_str()
                    .ok_or("missing label")?
                    .into(),
                data_classes: vec![],
            },
        );
    }
    Ok(ResolvedPolicy {
        version: 1,
        release,
        environment: if release {
            Environment::Production
        } else {
            Environment::Dev
        },
        network,
        features,
        pins,
    })
}

/// Hand the workers the policy just read, or the all-off placeholder when none could be read. The flag and the
/// policy change together under the policy's write lock, and [`loaded_policy`] reads both under its read lock.
fn publish(policy: &Policy, loaded: &AtomicBool, next: Option<ResolvedPolicy>) {
    let mut held = policy.write().unwrap_or_else(|p| p.into_inner());
    loaded.store(next.is_some(), Ordering::SeqCst);
    *held = next.unwrap_or_else(ResolvedPolicy::all_off);
}

/// The policy to run a step against, when one has been read from the core. A step never runs against the all-off
/// placeholder: it would fail the download for good (`feature_off`) instead of waiting for the policy.
fn loaded_policy(policy: &Policy, loaded: &AtomicBool) -> Option<ResolvedPolicy> {
    let held = policy.read().unwrap_or_else(|p| p.into_inner());
    loaded.load(Ordering::SeqCst).then(|| held.clone())
}

fn policy_client() -> reqwest::Result<reqwest::Client> {
    // reqwest's rustls-no-provider build needs a process default even for an HTTP-only core client.
    // Keep an existing provider when another caller has already initialized it.
    let _ = rustls::crypto::ring::default_provider().install_default();
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs_f64(keys::NET_CONNECT_TIMEOUT_S))
        .build()
}

fn monitor(
    core: &Supervisor,
    stop: &AtomicBool,
    policy: &Policy,
    loaded: &AtomicBool,
    release: bool,
) {
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(r) => r,
        Err(_) => return,
    };
    let client = match policy_client() {
        Ok(c) => c,
        Err(_) => return,
    };
    while !stop.load(Ordering::SeqCst) {
        let next = core.launch_info(Duration::ZERO).and_then(|info| {
            runtime.block_on(async {
                let response = client
                    .get(format!("{}/v1/connectivity", info.base_url))
                    .header("Authorization", format!("Bearer {}", info.token))
                    .header("Origin", "tauri://localhost")
                    .send()
                    .await
                    .ok()?;
                if !response.status().is_success() {
                    return None;
                }
                let bytes = response.bytes().await.ok()?;
                let value: Value = serde_json::from_slice(&bytes).ok()?;
                resolved(&value, release).ok()
            })
        });
        publish(policy, loaded, next);
        let until = Instant::now() + Duration::from_millis(keys::DOWNLOAD_POLICY_POLL_MS as u64);
        while Instant::now() < until && !stop.load(Ordering::SeqCst) {
            thread::sleep(poll());
        }
    }
}

struct Space;
impl Disk for Space {
    fn free_bytes(&self, path: &Path) -> u64 {
        sysinfo::Disks::new_with_refreshed_list()
            .iter()
            .filter(|d| path.starts_with(d.mount_point()))
            .max_by_key(|d| d.mount_point().components().count())
            .map_or(0, |d| d.available_space())
    }
}

struct Ranges {
    http: Https,
    sizes: BTreeMap<String, u64>,
}
impl Transport for Ranges {
    fn fetch(
        &mut self,
        url: &str,
        offset: u64,
        len: u64,
    ) -> Result<Vec<u8>, downloads::FetchError> {
        self.http.file_size(*self.sizes.get(url).unwrap_or(&0));
        self.http.fetch(url, offset, len)
    }
}

fn flush(core: &Supervisor, download: &mut Download, last: &Arc<Mutex<DownloadProgress>>) {
    for frame in std::mem::take(&mut download.outbox) {
        if frame["type"] == "control.download_state" {
            if let Ok(ToCore::DownloadState(progress)) = serde_json::from_value::<ToCore>(frame) {
                *last.lock().unwrap_or_else(|p| p.into_inner()) = progress.clone();
                core.send(&ToCore::DownloadState(progress));
            }
        } else if frame["state"] == "blocked" {
            core.send(&ToCore::EgressNotice(EgressNotice { notice: frame }));
        }
    }
    download.ledger.clear(); // HTTP records each actual destination, including allowed redirects.
}

#[allow(clippy::too_many_arguments)]
fn work(
    core: &Arc<Supervisor>,
    job: Job,
    data: &Path,
    policy: Policy,
    stop: &Arc<AtomicBool>,
    loaded: &AtomicBool,
    interrupted: Arc<AtomicBool>,
    commands: mpsc::Receiver<(DownloadControlAction, Option<DownloadLimits>)>,
    last: Arc<Mutex<DownloadProgress>>,
) {
    let folder = data.join("models").join("download-cache");
    let existing = folder.join(&job.download_id).join("journal.json").exists();
    let opened = if existing {
        Download::reopen(&folder, &job.download_id)
    } else {
        Download::create(job.clone(), &folder)
    };
    let mut download = match opened {
        Ok(d) if d.job() == &job => d,
        _ => {
            let progress = failed(&job.download_id, "io");
            *last.lock().unwrap_or_else(|p| p.into_inner()) = progress.clone();
            core.send(&ToCore::DownloadState(progress));
            return;
        }
    };
    let mut http = match Https::new(policy.clone(), interrupted.clone(), stop.clone()) {
        Ok(h) => h,
        Err(_) => {
            let progress = failed(&job.download_id, "tls_unavailable");
            *last.lock().unwrap_or_else(|p| p.into_inner()) = progress.clone();
            core.send(&ToCore::DownloadState(progress));
            return;
        }
    };
    let send = core.clone();
    let progress = last.clone();
    http.events(Arc::new(move |allowed, state| {
        if state == NoticeState::Started {
            let mut started = progress.lock().unwrap_or_else(|p| p.into_inner()).clone();
            started.state = DownloadStateState::Downloading;
            send.send(&ToCore::DownloadState(started));
            // Only the shell's own features and payload classes are ledgered here (ARC-10); `net::check` allows
            // nothing else.
            if let (Ok(feature), Ok(payload_class)) =
                (allowed.feature.parse(), allowed.payload_class.parse())
            {
                send.send(&ToCore::EgressLedger(EgressLedger {
                    at_ms: now_ms(),
                    feature,
                    destination: allowed.host.clone(),
                    bytes: allowed.bytes,
                    payload_class,
                }));
            }
        }
        send.send(&ToCore::EgressNotice(EgressNotice {
            notice: allowed.notice(state),
        }));
    }));
    let sizes = job
        .files
        .iter()
        .map(|f| (f.url.clone(), f.size_bytes))
        .collect();
    let mut transport = Ranges { http, sizes };
    let mut limits = downloads::Limits::from_keys(download_http::limits());
    let mut next = Instant::now();
    flush(core, &mut download, &last);
    while !stop.load(Ordering::SeqCst) {
        for (action, configuration) in commands.try_iter() {
            let _ = match action {
                DownloadControlAction::Pause => download.pause(),
                DownloadControlAction::Resume => {
                    interrupted.store(false, Ordering::SeqCst);
                    download.resume()
                }
                DownloadControlAction::Cancel => download.cancel(),
                DownloadControlAction::Configure => {
                    if let Some(configuration) = configuration {
                        limits.bandwidth_cap = configuration.bandwidth_bytes_per_s;
                        limits.net = download_http::limits();
                        if configuration.allow_metered {
                            limits.net.metered_large_download_bytes = u64::MAX;
                        }
                        transport.http.allow_metered(configuration.allow_metered);
                        interrupted.store(false, Ordering::SeqCst);
                        // A changed cap takes effect at the next chunk, even if the previous cap had a long wait.
                        next = Instant::now();
                    }
                    Ok(())
                }
            };
        }
        flush(core, &mut download, &last);
        if download.state.is_terminal() {
            break;
        }
        if Instant::now() >= next
            && let Some(current) = loaded_policy(&policy, loaded)
        {
            match download.step(&current, &limits, &mut transport, &Space, now_ms()) {
                Step::Progress { wait } => next = Instant::now() + wait,
                Step::Idle => {
                    next =
                        Instant::now() + Duration::from_millis(keys::DOWNLOAD_POLICY_POLL_MS as u64)
                }
                _ => {}
            }
            flush(core, &mut download, &last);
        }
        thread::sleep(poll());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn policy_client_initializes_crypto_on_cold_start() {
        assert!(policy_client().is_ok());
    }

    fn online() -> ResolvedPolicy {
        ResolvedPolicy::from_json(
            &serde_json::json!({
                "version": 1, "environment": "dev", "release": false, "network": "online",
                "features": { "downloads": { "enabled": true, "hosts": ["downloads.dev.jana.invalid"],
                    "payload_classes": ["download_request"], "authenticated": false,
                    "destination_label": "Models", "data_classes": [] } },
                "pins": {},
            })
            .to_string(),
        )
        .unwrap()
    }

    /// While the policy is refreshed (and while the core restarts and none can be read), a worker either waits or
    /// steps against a policy the core gave: never against the all-off placeholder, which would fail the download
    /// for good.
    #[test]
    fn steps_never_see_the_placeholder_policy() {
        let policy: Policy = Arc::new(RwLock::new(ResolvedPolicy::all_off()));
        let loaded = Arc::new(AtomicBool::new(false));
        assert!(loaded_policy(&policy, &loaded).is_none());
        let done = Arc::new(AtomicBool::new(false));
        let refresher = {
            let (policy, loaded, done) = (policy.clone(), loaded.clone(), done.clone());
            thread::spawn(move || {
                for i in 0..20_000 {
                    publish(&policy, &loaded, (i % 2 == 0).then(online));
                }
                done.store(true, Ordering::SeqCst);
            })
        };
        let mut stepped = 0;
        while !done.load(Ordering::SeqCst) {
            if let Some(current) = loaded_policy(&policy, &loaded) {
                assert!(current.features.contains_key("downloads"));
                stepped += 1;
            }
        }
        refresher.join().unwrap();
        assert!(stepped > 0);
    }

    /// The part files kept at start are those of downloads the core still means to finish.
    #[test]
    fn tracked_downloads_follow_the_core_record() {
        let data = std::env::temp_dir().join(format!("jana-tracked-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&data);
        std::fs::create_dir_all(data.join("models")).unwrap();
        assert_eq!(tracked_downloads(&data), Some(BTreeSet::new()));
        let record = |state: &str| serde_json::json!({"state": state});
        std::fs::write(
            data.join("models/downloads.json"),
            serde_json::json!({
                "dl_a": record("downloading"), "dl_b": record("paused"), "dl_c": record("failed"),
                "dl_d": record("done"), "dl_e": record("cancelled"), "dl_f": record("queued"),
            })
            .to_string(),
        )
        .unwrap();
        assert_eq!(
            tracked_downloads(&data),
            Some(["dl_a", "dl_b", "dl_f"].map(String::from).into())
        );
        std::fs::write(data.join("models/downloads.json"), b"{not json").unwrap();
        assert_eq!(
            tracked_downloads(&data),
            None,
            "unreadable: nothing is removed"
        );
        let _ = std::fs::remove_dir_all(data);
    }
}
