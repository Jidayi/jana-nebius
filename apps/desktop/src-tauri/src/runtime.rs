//! Starting and supervising the model runtime, `llama-server` (ARC-02, ARC-22 to ARC-24, MDL-19, SEC-24).
//!
//! Once the agent core reports `control.ready`, the shell reads the launch plan the core wrote for that epoch
//! (`<core data>/runtime/launch.json`, documented in the core's `engine.runtime_link`). A plan without a model means
//! content-only: nothing is started. Otherwise each launch gets a fresh random key, written to a 0600 key file the
//! runtime reads at start (never argv, the environment or a log) and removed once the runtime answers HTTP, and a
//! free loopback port. The runtime runs in its own process group with the plan's arguments; when it answers, the
//! shell sends `control.runtime_endpoint {url, key, model}` and the core proves readiness with a real generation
//! (MDL-20). A core restart gets the same endpoint again.
//!
//! A crash restarts the runtime after the plan's backoff with a new key and port (and a new endpoint). Past the
//! plan's restarts inside its window, the next smaller model in the plan gets one turn under the same policy; after
//! that the shell gives up and the core, which sees the runtime gone, reports content-only (MDL-19). On quit the
//! runtime is stopped after the core, inside the ARC-23 deadline. Every launch is recorded so a later start can end
//! an orphan (ARC-24).
//!
//! The runtime yields to the app (ARC-31): the plan's `priority` names a niceness, applied on Unix by starting it
//! through the system `nice` (so every thread it makes inherits it) and on Windows by the below-normal priority class,
//! and a number of physical cores to leave free, so `--threads` is the physical cores minus that, at least one. The
//! memory it may use is bounded by the plan's context size, which the core fits with the configured headroom.
//!
//! Builds (PLT-04). The supervisor is given the llama.cpp builds this machine may run, best first (`variants`). A
//! build is proven once the core reports `ready` while it runs, that is once its touch generation passed (ARC-22). A
//! build that ends before that, by crashing, never answering, failing to start or the core reporting its touch
//! generation failed, is set aside with why and the next build down starts the same model, outside the restart
//! policy; past the last build there is no runtime (content-only). What runs and why is written next to the plan as
//! `variant.json` for the core's health panel (OBS-15).

use crate::control::{Redacted, RuntimeEndpoint, ToCore};
use crate::generated::keys;
use crate::launch::Token;
use crate::orphans;
use crate::process_tree::{self, Tree};
use crate::variants::{Variant, exit_reason};
use serde::Deserialize;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

/// How often the supervisor looks at the runtime and the core; a crash is noticed within one tick.
const TICK: Duration = Duration::from_millis(50);
/// The plan lists the chosen model and at most one next smaller model (MDL-19).
const MAX_ATTEMPTS: usize = 2;

/// The shell side of the control channel, as the runtime supervisor uses it.
pub trait CoreLink: Send + Sync {
    /// The epoch of the core process that is ready now, if one is.
    fn ready_epoch(&self) -> Option<String>;
    /// Send a control message to that core.
    fn send(&self, message: &ToCore) -> bool;
    /// The core's last reported readiness (TABLE ARC-22b), when known: `ready` proves a build (PLT-04).
    fn readiness(&self) -> Option<String> {
        None
    }
}

/// The runtime program: the bundled `llama-server`, or in development a stand-in (a local build, a fake).
#[derive(Debug, Clone)]
pub struct RuntimeCommand {
    pub program: PathBuf,
    pub prefix_args: Vec<String>,
}

/// One llama.cpp build to try: its variant (none for a development stand-in, which is never set aside) and program.
#[derive(Debug, Clone)]
pub struct Build {
    pub variant: Option<Variant>,
    pub command: RuntimeCommand,
}

/// The builds this machine may run, best first, and those left out with why (PLT-04).
#[derive(Debug, Clone, Default)]
pub struct Builds {
    pub ladder: Vec<Build>,
    pub skipped: Vec<(Variant, String)>,
}

impl Builds {
    /// One program with no variant: development and tests that do not exercise PLT-04.
    pub fn single(command: RuntimeCommand) -> Builds {
        Builds {
            ladder: vec![Build {
                variant: None,
                command,
            }],
            skipped: vec![],
        }
    }
}

#[derive(Debug, Clone)]
pub struct RuntimePolicy {
    /// How long a launch may take to answer HTTP before it counts as a failed start.
    pub start_deadline: Duration,
    /// How long a polite stop may take before the runtime is killed (ARC-23).
    pub step_deadline: Duration,
}

impl Default for RuntimePolicy {
    fn default() -> Self {
        RuntimePolicy {
            start_deadline: Duration::from_secs_f64(keys::RUNTIME_START_DEADLINE_S),
            step_deadline: Duration::from_secs_f64(keys::SHUTDOWN_GRACE_S),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Attempt {
    pub model: String,
    pub args: Vec<String>,
}

/// The restart policy, from the router configuration via the plan (MDL-19, canonical for TABLE ARC-24a).
#[derive(Debug, Clone, Deserialize)]
pub struct Restart {
    pub backoff_s: Vec<f64>,
    pub max_restarts: usize,
    pub window_s: f64,
}

/// How the runtime yields to the app (ARC-31), from the core's configuration via the plan.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Priority {
    /// The Unix niceness to start it with; 0 starts it at normal priority.
    pub niceness: u32,
    /// Physical cores left to the app and the system: the runtime gets the rest, at least one.
    pub reserved_cores: usize,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Plan {
    pub plan_version: u32,
    pub epoch: String,
    pub model: Option<String>,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub attempts: Vec<Attempt>,
    pub restart: Restart,
    /// Absent from a plan written before ARC-31: the runtime then starts at normal priority with its own threads.
    #[serde(default)]
    pub priority: Option<Priority>,
}

/// The plan the core with this epoch wrote, or why there is none to act on.
pub fn read_plan(path: &Path, epoch: &str) -> Result<Plan, String> {
    let bytes = fs::read(path).map_err(|_| "no_plan".to_string())?;
    let plan: Plan = serde_json::from_slice(&bytes).map_err(|_| "invalid_plan".to_string())?;
    if plan.plan_version != 1 {
        return Err("unknown_plan_version".into());
    }
    if plan.epoch != epoch {
        return Err("stale_plan".into());
    }
    Ok(plan)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeState {
    WaitingForCore,
    /// Nothing to start: the plan names no model (content-only), or there is no usable plan.
    NoModel {
        reason: String,
    },
    Starting {
        model: String,
    },
    Running {
        model: String,
        port: u16,
    },
    Restarting {
        model: String,
        crashes: usize,
    },
    /// The restart policy is spent, the runtime program cannot be started, or no build this machine may run passed
    /// its touch generation (`no_runtime_variant`, PLT-04): content-only (MDL-19).
    GaveUp {
        reason: String,
    },
    Stopped,
}

struct Shared {
    state: RuntimeState,
    pid: Option<u32>,
    launches: usize,
    stop: bool,
    step_deadline: Duration,
}

pub struct RuntimeSupervisor {
    shared: Arc<(Mutex<Shared>, Condvar)>,
    thread: Mutex<Option<JoinHandle<()>>>,
}

fn lock(shared: &(Mutex<Shared>, Condvar)) -> MutexGuard<'_, Shared> {
    shared
        .0
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn set_state(shared: &(Mutex<Shared>, Condvar), state: RuntimeState) {
    lock(shared).state = state;
    shared.1.notify_all();
}

/// Wait up to `timeout`, or less if a stop is asked for. Returns whether a stop was asked for.
fn pause(shared: &(Mutex<Shared>, Condvar), timeout: Duration) -> bool {
    let guard = lock(shared);
    let (guard, _) = shared
        .1
        .wait_timeout_while(guard, timeout, |s| !s.stop)
        .unwrap_or_else(|e| e.into_inner());
    guard.stop
}

impl RuntimeSupervisor {
    /// Supervise the runtime for the core behind `core` with one program. Orphans recorded by a previous run are
    /// ended first.
    pub fn start(
        core: Arc<dyn CoreLink>,
        plan_path: PathBuf,
        command: RuntimeCommand,
        policy: RuntimePolicy,
        pid_file: Option<PathBuf>,
    ) -> RuntimeSupervisor {
        RuntimeSupervisor::start_builds(
            core,
            plan_path,
            Box::new(move || Builds::single(command)),
            policy,
            pid_file,
        )
    }

    /// Supervise the runtime with the builds `select` returns, best first (PLT-04). `select` runs on the supervisor's
    /// own thread, so probing the GPU never holds up the window.
    pub fn start_builds(
        core: Arc<dyn CoreLink>,
        plan_path: PathBuf,
        select: Box<dyn FnOnce() -> Builds + Send>,
        policy: RuntimePolicy,
        pid_file: Option<PathBuf>,
    ) -> RuntimeSupervisor {
        if let Some(path) = &pid_file {
            orphans::recover(path);
        }
        let shared = Arc::new((
            Mutex::new(Shared {
                state: RuntimeState::WaitingForCore,
                pid: None,
                launches: 0,
                stop: false,
                step_deadline: policy.step_deadline,
            }),
            Condvar::new(),
        ));
        let worker = {
            let shared = Arc::clone(&shared);
            thread::spawn(move || {
                let builds = select();
                let mut run = Run {
                    shared: &shared,
                    core: core.as_ref(),
                    builds: &builds,
                    build: 0,
                    proven: builds.ladder.first().is_none_or(|b| b.variant.is_none()),
                    fallbacks: Vec::new(),
                    policy: &policy,
                    pid_file: pid_file.as_deref(),
                    key_file: plan_path.with_file_name("key"),
                    variant_file: plan_path.with_file_name("variant.json"),
                    // `<core data>/runtime/launch.json` → `<core data>/crashes`, the core's crash inbox (OBS-16).
                    crashes: plan_path
                        .parent()
                        .and_then(Path::parent)
                        .map(|data| data.join("crashes")),
                    epoch: String::new(),
                    sent_to: None,
                };
                run.supervise(&plan_path);
            })
        };
        RuntimeSupervisor {
            shared,
            thread: Mutex::new(Some(worker)),
        }
    }

    pub fn state(&self) -> RuntimeState {
        lock(&self.shared).state.clone()
    }

    pub fn pid(&self) -> Option<u32> {
        lock(&self.shared).pid
    }

    /// Runtime processes started so far (the first launch, restarts and the smaller model's launches).
    pub fn launches(&self) -> usize {
        lock(&self.shared).launches
    }

    /// Wait until the state matches `want`, up to `timeout`.
    pub fn wait_for(&self, timeout: Duration, want: impl Fn(&RuntimeState) -> bool) -> bool {
        let deadline = Instant::now() + timeout;
        let mut guard = lock(&self.shared);
        while !want(&guard.state) {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return false;
            }
            guard = self
                .shared
                .1
                .wait_timeout(guard, left)
                .map(|(g, _)| g)
                .unwrap_or_else(|e| e.into_inner().0);
        }
        true
    }

    /// Quit (ARC-23, after the core): stop the runtime politely, kill it when `budget` (at most the step deadline)
    /// runs out. Returns how long it took.
    pub fn shutdown(&self, budget: Duration) -> Duration {
        let started = Instant::now();
        {
            let mut guard = lock(&self.shared);
            guard.stop = true;
            guard.step_deadline = guard.step_deadline.min(budget);
            self.shared.1.notify_all();
        }
        if let Some(handle) = self.thread.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = handle.join();
        }
        started.elapsed()
    }
}

enum Ended {
    /// It exited, or never answered within the start deadline: why, for the record (PLT-04).
    Crashed(String),
    /// The core's touch generation failed on a build not yet proven (PLT-04).
    TouchFailed,
    /// Another process answered on the launch's port before the runtime could bind it: the key is never sent there;
    /// the launch counts against the restart policy but does not set the build aside.
    PortTaken,
    Stopped,
    /// The program could not be started at all: restarting would not help.
    Unstartable,
}

struct Run<'a> {
    shared: &'a (Mutex<Shared>, Condvar),
    core: &'a dyn CoreLink,
    builds: &'a Builds,
    build: usize,
    /// The current build passed a touch generation, or is a stand-in that is never set aside.
    proven: bool,
    fallbacks: Vec<(Variant, String)>,
    policy: &'a RuntimePolicy,
    pid_file: Option<&'a Path>,
    key_file: PathBuf,
    variant_file: PathBuf,
    crashes: Option<PathBuf>,
    epoch: String,
    sent_to: Option<String>,
}

impl Run<'_> {
    fn stopping(&self) -> bool {
        lock(self.shared).stop
    }

    fn finish(&self, state: RuntimeState) {
        let _ = fs::remove_file(&self.key_file);
        if let Some(path) = self.pid_file {
            let _ = fs::remove_file(path);
        }
        set_state(self.shared, state);
    }

    fn supervise(&mut self, plan_path: &Path) {
        let epoch = loop {
            if self.stopping() {
                return self.finish(RuntimeState::Stopped);
            }
            if let Some(epoch) = self.core.ready_epoch() {
                break epoch;
            }
            pause(self.shared, TICK);
        };
        self.epoch = epoch.clone();
        let plan = match read_plan(plan_path, &epoch) {
            Ok(plan) if plan.model.is_some() && !plan.attempts.is_empty() => plan,
            Ok(plan) => {
                let reason = plan.reason.unwrap_or_else(|| "no_model".into());
                return self.idle(RuntimeState::NoModel { reason });
            }
            Err(reason) => return self.idle(RuntimeState::NoModel { reason }),
        };
        let window = Duration::from_secs_f64(plan.restart.window_s);
        let attempts = plan.attempts.len().min(MAX_ATTEMPTS);
        let mut attempt = 0;
        let mut crashes: Vec<Instant> = Vec::new();
        self.write_variant();
        if self.builds.ladder.is_empty() {
            return self.finish(RuntimeState::GaveUp {
                reason: "no_runtime_variant".into(),
            });
        }
        loop {
            let chosen = &plan.attempts[attempt];
            let ended = self.launch(chosen, plan.priority.as_ref());
            if !self.proven && !matches!(ended, Ended::Stopped | Ended::PortTaken) {
                // PLT-04: the build failed before its first touch generation passed; the next one down starts.
                let why = match ended {
                    Ended::Crashed(why) => why,
                    Ended::TouchFailed => "its first generation failed".into(),
                    _ => "could not be started".into(),
                };
                if self.next_build(why) {
                    continue;
                }
                return self.finish(RuntimeState::GaveUp {
                    reason: "no_runtime_variant".into(),
                });
            }
            match ended {
                Ended::Stopped => return self.finish(RuntimeState::Stopped),
                Ended::Unstartable => {
                    return self.finish(RuntimeState::GaveUp {
                        reason: "runtime_unstartable".into(),
                    });
                }
                Ended::Crashed(_) | Ended::TouchFailed | Ended::PortTaken => {}
            }
            let now = Instant::now();
            crashes.retain(|t| now.duration_since(*t) < window);
            crashes.push(now);
            if crashes.len() > plan.restart.max_restarts {
                if attempt + 1 < attempts {
                    attempt += 1; // the next smaller installed model, once (MDL-19)
                    crashes.clear();
                    continue;
                }
                return self.finish(RuntimeState::GaveUp {
                    reason: "restart_limit".into(),
                });
            }
            set_state(
                self.shared,
                RuntimeState::Restarting {
                    model: chosen.model.clone(),
                    crashes: crashes.len(),
                },
            );
            let wait = plan
                .restart
                .backoff_s
                .get(crashes.len() - 1)
                .or(plan.restart.backoff_s.last())
                .map(|s| Duration::from_secs_f64(*s))
                .unwrap_or_default();
            if pause(self.shared, wait) {
                return self.finish(RuntimeState::Stopped);
            }
        }
    }

    /// Set the current build aside with why and move to the next; false when none is left.
    fn next_build(&mut self, why: String) -> bool {
        if let Some(variant) = self.builds.ladder[self.build].variant {
            self.fallbacks.push((variant, why));
        }
        self.build += 1;
        self.proven = self
            .builds
            .ladder
            .get(self.build)
            .is_some_and(|b| b.variant.is_none());
        self.write_variant();
        self.build < self.builds.ladder.len()
    }

    /// The build in use and why it is not the first choice, for this core's health panel (PLT-04, OBS-15).
    fn write_variant(&self) {
        let named = |list: &[(Variant, String)]| -> Vec<serde_json::Value> {
            list.iter()
                .map(|(v, why)| serde_json::json!({"variant": v.name(), "reason": why}))
                .collect()
        };
        let current = self
            .builds
            .ladder
            .get(self.build)
            .and_then(|b| b.variant)
            .map(Variant::name);
        if current.is_none() && self.fallbacks.is_empty() && self.builds.skipped.is_empty() {
            return; // a development stand-in: nothing to report
        }
        let record = serde_json::json!({
            "epoch": self.epoch,
            "variant": current,
            "fallbacks": named(&self.fallbacks),
            "rejected": named(&self.builds.skipped),
        });
        let tmp = self.variant_file.with_extension("tmp");
        if fs::write(&tmp, record.to_string()).is_ok() {
            let _ = fs::rename(&tmp, &self.variant_file);
        }
    }

    /// Nothing to supervise: wait for quit.
    fn idle(&self, state: RuntimeState) {
        set_state(self.shared, state);
        while !pause(self.shared, Duration::from_secs(3600)) {}
        let mut guard = lock(self.shared);
        guard.state = RuntimeState::Stopped;
        self.shared.1.notify_all();
    }

    /// One launch, from spawn to its end.
    fn launch(&mut self, attempt: &Attempt, priority: Option<&Priority>) -> Ended {
        set_state(
            self.shared,
            RuntimeState::Starting {
                model: attempt.model.clone(),
            },
        );
        let key = Token::new();
        if write_key(&self.key_file, key.reveal()).is_err() {
            return Ended::Unstartable;
        }
        let Some(port) = free_port() else {
            return Ended::Crashed("no free loopback port".into());
        };
        let nice = priority
            .filter(|p| p.niceness > 0)
            .and_then(|_| nice_program());
        let cores = sysinfo::System::physical_core_count();
        let command = &self.builds.ladder[self.build].command;
        let mut child = match runtime_command(
            command,
            attempt,
            port,
            &self.key_file,
            priority,
            cores,
            nice.as_deref(),
        )
        .spawn()
        {
            Ok(child) => child,
            Err(_) => return Ended::Unstartable,
        };
        let pid = child.id();
        let tree = Tree::adopt(&child);
        let stderr = StderrTail::follow(child.stderr.take(), keys::CRASH_STDERR_TAIL_LINES);
        if let Some(path) = self.pid_file {
            orphans::track(path, pid);
        }
        // Started through `nice`, the process becomes the runtime once `nice` executes it: record it again then,
        // so an orphan check compares against the runtime's own executable (ARC-24).
        let mut wrapped = nice.filter(|_| self.pid_file.is_some());
        {
            let mut guard = lock(self.shared);
            guard.pid = Some(pid);
            guard.launches += 1;
        }
        let started = Instant::now();
        let ended = loop {
            if self.stopping() {
                break Ended::Stopped;
            }
            if let Some(why) = exited(&mut child) {
                break Ended::Crashed(format!("{why} before it answered"));
            }
            if let (Some(wrapper), Some(path)) = (wrapped.as_deref(), self.pid_file)
                && orphans::identify(pid).is_some_and(|r| Path::new(&r.exe) != wrapper)
            {
                orphans::track(path, pid);
                wrapped = None;
            }
            if answers_http(port) {
                if port_held_by_another(port, pid) {
                    break Ended::PortTaken;
                }
                break self.serve(&mut child, attempt, port, &key);
            }
            if started.elapsed() > self.policy.start_deadline {
                // a launch that never answers is a failed start
                break Ended::Crashed("did not answer within the start deadline".into());
            }
            pause(self.shared, TICK);
        };
        let _ = fs::remove_file(&self.key_file);
        let ended_by_itself = child.try_wait().ok().flatten();
        self.end(&tree, &mut child);
        if let (Ended::Crashed(_), Some(status)) = (&ended, ended_by_itself) {
            self.record_crash(status.code(), &stderr.lines());
        }
        lock(self.shared).pid = None;
        ended
    }

    /// A runtime that ended by itself leaves a crash record with its exit code and stderr tail in the core's crash
    /// inbox (OBS-16); a stop, a kill for a failed start or a port taken by another process is not a crash.
    fn record_crash(&self, exit_code: Option<i32>, stderr: &[String]) {
        if let Some(crashes) = &self.crashes {
            let _ = crate::crash::runtime_exit(
                crashes,
                env!("CARGO_PKG_VERSION"),
                exit_code,
                stderr,
                keys::CRASH_STDERR_TAIL_LINES,
            );
        }
    }

    /// The runtime answers: hand the core its endpoint, then watch for a crash, a core restart or quit.
    fn serve(&mut self, child: &mut Child, attempt: &Attempt, port: u16, key: &Token) -> Ended {
        let _ = fs::remove_file(&self.key_file); // read at start; nothing on disk holds the key from here on
        set_state(
            self.shared,
            RuntimeState::Running {
                model: attempt.model.clone(),
                port,
            },
        );
        self.sent_to = None;
        // Whether the core has taken this launch up since its endpoint went out: it reported `model_loading`, or its
        // readiness was something other than `degraded` when the endpoint went out (a fast failure may skip a tick).
        let mut taken_up = false;
        loop {
            if self.stopping() {
                return Ended::Stopped;
            }
            // Read the core's readiness before looking for an exit: a touch generation that passed just before a
            // crash still proves the build.
            let mut touch_failed = false;
            if self.sent_to.is_some() && !self.proven {
                match self.core.readiness().as_deref() {
                    Some("ready") => self.proven = true,
                    Some("model_loading") => taken_up = true,
                    Some("degraded") if taken_up => touch_failed = true,
                    _ => {}
                }
            }
            if let Some(why) = exited(child) {
                let during = if self.sent_to.is_some() && !self.proven {
                    "during its first generation"
                } else {
                    "while running"
                };
                return Ended::Crashed(format!("{why} {during}"));
            }
            if touch_failed {
                return Ended::TouchFailed;
            }
            let epoch = self.core.ready_epoch();
            if epoch.is_some() && epoch != self.sent_to {
                let sent = self.core.send(&ToCore::RuntimeEndpoint(RuntimeEndpoint {
                    url: format!("http://127.0.0.1:{port}"),
                    key: Redacted::new(key.reveal()),
                    model: attempt.model.clone(),
                }));
                if sent {
                    self.sent_to = epoch;
                    taken_up |= self.core.readiness().as_deref() != Some("degraded");
                }
            }
            pause(self.shared, TICK);
        }
    }

    /// End a launch's process tree: politely, then by force after the step deadline. The forced end also kills the
    /// process itself, so the final wait never blocks on a live runtime (Windows has no polite signal).
    fn end(&self, tree: &Tree, child: &mut Child) {
        if matches!(child.try_wait(), Ok(None)) {
            tree.terminate();
            let deadline = Instant::now() + lock(self.shared).step_deadline;
            while matches!(child.try_wait(), Ok(None)) && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(10));
            }
            if matches!(child.try_wait(), Ok(None)) {
                process_tree::kill_child(tree, child);
            }
        }
        let _ = child.wait();
        if let Some(path) = self.pid_file {
            let _ = fs::remove_file(path);
        }
    }
}

/// Why the process has ended, or None while it runs.
fn exited(child: &mut Child) -> Option<String> {
    match child.try_wait() {
        Ok(None) => None,
        Ok(Some(status)) => Some(exit_reason(&status)),
        Err(_) => Some("ended".into()),
    }
}

/// The launch's key, readable by this user only.
fn write_key(path: &Path, key: &str) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let _ = fs::remove_file(path);
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)?.write_all(key.as_bytes())
}

fn free_port() -> Option<u16> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).ok()?;
    listener.local_addr().ok().map(|a| a.port())
}

/// The system `nice`, when this platform has one where it is expected.
fn nice_program() -> Option<PathBuf> {
    if !cfg!(unix) {
        return None;
    }
    ["/usr/bin/nice", "/bin/nice"]
        .iter()
        .map(PathBuf::from)
        .find(|p| p.is_file())
}

/// The runtime's thread count: the physical cores minus those the plan leaves free, at least one; none when the
/// core count is unknown (the runtime then chooses).
pub fn runtime_threads(
    priority: Option<&Priority>,
    physical_cores: Option<usize>,
) -> Option<usize> {
    let reserved = priority?.reserved_cores;
    physical_cores.map(|cores| cores.saturating_sub(reserved).max(1))
}

/// One launch's command line: the plan's arguments, the launch's port and key file, the thread cap and, through
/// `nice` (Unix) or the priority class (Windows), the lower priority (ARC-31). The plan's own `--threads` wins.
pub fn runtime_command(
    command: &RuntimeCommand,
    attempt: &Attempt,
    port: u16,
    key_file: &Path,
    priority: Option<&Priority>,
    physical_cores: Option<usize>,
    nice: Option<&Path>,
) -> Command {
    let mut cmd = match (nice, priority) {
        (Some(nice), Some(priority)) => {
            let mut cmd = Command::new(nice);
            cmd.arg("-n")
                .arg(priority.niceness.to_string())
                .arg(&command.program);
            cmd
        }
        _ => Command::new(&command.program),
    };
    cmd.args(&command.prefix_args)
        .args(&attempt.args)
        .arg("--port")
        .arg(port.to_string())
        .arg("--api-key-file")
        .arg(key_file);
    let has_threads = attempt.args.iter().any(|a| a == "--threads" || a == "-t");
    if let Some(threads) = runtime_threads(priority, physical_cores).filter(|_| !has_threads) {
        cmd.arg("--threads").arg(threads.to_string());
    }
    // stderr is read for the crash record's tail (OBS-16); nothing else of the runtime's output is kept.
    cmd.stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    process_tree::isolate(&mut cmd); // quitting or a restart ends it and anything it started
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const BELOW_NORMAL_PRIORITY_CLASS: u32 = 0x0000_4000;
        if priority.is_some_and(|p| p.niceness > 0) {
            cmd.creation_flags(BELOW_NORMAL_PRIORITY_CLASS);
        }
    }
    cmd
}

/// Whether something speaks HTTP on the port (any status; readiness is the core's touch generation, MDL-20).
fn answers_http(port: u16) -> bool {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(200)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut head = [0u8; 5];
    stream.read_exact(&mut head).is_ok() && &head == b"HTTP/"
}

/// The words a free-form diagnostic line may hold (OBS-16, OBS-19, PRV-09), shared with the core's crash store.
const DIAGNOSTIC_WORDS: &str =
    include_str!("../../../../services/agent-core/agent_core/trace/diagnostic_words.json");

fn diagnostic_words() -> &'static std::collections::HashSet<String> {
    static WORDS: std::sync::OnceLock<std::collections::HashSet<String>> =
        std::sync::OnceLock::new();
    WORDS.get_or_init(|| {
        serde_json::from_str::<serde_json::Value>(DIAGNOSTIC_WORDS)
            .ok()
            .and_then(|doc| doc.get("words").cloned())
            .and_then(|words| serde_json::from_value::<Vec<String>>(words).ok())
            .unwrap_or_default()
            .into_iter()
            .collect()
    })
}

/// Whether a stderr line holds diagnostics only: every plain word in it is in the diagnostic vocabulary. Paths,
/// dotted names, numbers, hex, identifiers (with a digit, an underscore or inner capitals) and single letters other
/// than "I" are not words. The same rule as the core's `trace.logs.diagnostic`: a line that could be a prompt, an
/// answer or anything a student wrote is withheld.
pub fn diagnostic(line: &str) -> bool {
    let words = diagnostic_words();
    for chunk in line.split_whitespace() {
        let dotted = chunk.as_bytes().windows(3).any(|w| {
            (w[0].is_ascii_alphanumeric() || w[0] == b'_')
                && w[1] == b'.'
                && (w[2].is_ascii_alphabetic() || w[2] == b'_')
        });
        if chunk.contains('/') || chunk.contains('\\') || dotted {
            continue;
        }
        for part in chunk.split(|c: char| !(c.is_ascii_alphanumeric() || c == '_')) {
            if part.is_empty() || part.chars().any(|c| c.is_ascii_digit() || c == '_') {
                continue;
            }
            let camel = part
                .as_bytes()
                .windows(2)
                .any(|w| w[0].is_ascii_lowercase() && w[1].is_ascii_uppercase());
            if camel || (part.len() == 1 && part != "I" && part != "i") {
                continue;
            }
            if !words.contains(&part.to_ascii_lowercase()) {
                return false;
            }
        }
    }
    true
}

fn withheld_line(count: usize) -> String {
    format!(
        "[withheld {count} line{}]",
        if count == 1 { "" } else { "s" }
    )
}

/// Free-form lines as a crash record or a log may hold them: diagnostic lines kept, each run of other lines replaced
/// by `[withheld N lines]`, so no prompt, answer or student text leaves the process's own memory.
pub fn diagnostic_lines<'a>(lines: impl IntoIterator<Item = &'a str>) -> Vec<String> {
    let mut out = Vec::new();
    let mut withheld = 0usize;
    for line in lines {
        if diagnostic(line) {
            if withheld > 0 {
                out.push(withheld_line(withheld));
                withheld = 0;
            }
            out.push(line.chars().take(300).collect());
        } else {
            withheld += 1;
        }
    }
    if withheld > 0 {
        out.push(withheld_line(withheld));
    }
    out
}

/// Pass a child's stderr on to the shell's own, diagnostic lines only (OBS-19): a run of other lines is written as
/// `[withheld N lines]` when the next diagnostic line or the end comes. Read on a thread of its own.
pub fn forward_diagnostics<R: Read + Send + 'static>(stderr: Option<R>) {
    if let Some(stderr) = stderr {
        forward_diagnostics_to(stderr, std::io::stderr());
    }
}

/// `forward_diagnostics` into any writer; the thread ends when the child's stderr closes.
pub fn forward_diagnostics_to<R: Read + Send + 'static, W: Write + Send + 'static>(
    stderr: R,
    mut out: W,
) -> JoinHandle<()> {
    thread::spawn(move || {
        let mut withheld = 0usize;
        for line in BufReader::new(stderr).lines() {
            let Ok(line) = line else { break };
            if diagnostic(&line) {
                if withheld > 0 {
                    let _ = writeln!(out, "{}", withheld_line(withheld));
                    withheld = 0;
                }
                let _ = writeln!(out, "{}", line.chars().take(300).collect::<String>());
            } else {
                withheld += 1;
            }
        }
        if withheld > 0 {
            let _ = writeln!(out, "{}", withheld_line(withheld));
        }
        let _ = out.flush();
    })
}

/// The last `keep` lines a process wrote to stderr, read on a thread of their own so the pipe never fills. Only
/// diagnostic lines leave it (`lines`): the runtime's stderr can echo a prompt (OBS-16, OBS-19).
#[derive(Clone, Default)]
pub struct StderrTail(Arc<Mutex<std::collections::VecDeque<String>>>);

impl StderrTail {
    pub fn follow(stderr: Option<std::process::ChildStderr>, keep: usize) -> StderrTail {
        let tail = StderrTail::default();
        if let Some(stderr) = stderr {
            let lines = tail.0.clone();
            thread::spawn(move || {
                for line in BufReader::new(stderr).lines() {
                    let Ok(line) = line else { break };
                    let mut held = lines.lock().unwrap_or_else(|p| p.into_inner());
                    if held.len() >= keep.max(1) {
                        held.pop_front();
                    }
                    held.push_back(line);
                }
            });
        }
        tail
    }

    /// The held lines with every non-diagnostic run withheld (`diagnostic_lines`).
    pub fn lines(&self) -> Vec<String> {
        let held = self.0.lock().unwrap_or_else(|p| p.into_inner());
        diagnostic_lines(held.iter().map(String::as_str))
    }
}

/// Whether something other than process `pid` answers on loopback `port`: a process that took the port between the
/// shell choosing it and the runtime binding it, which must never be handed the launch key. Refuses only on evidence
/// that `pid` holds no listener on the port; where this platform cannot tell, the answer counts as the runtime's.
pub fn port_held_by_another(port: u16, pid: u32) -> bool {
    listens_on(port, pid) == Some(false)
}

/// Whether `pid` holds the loopback TCP listener on `port`, when the system can tell (macOS: `lsof` on that one
/// process, which needs no privileges).
#[cfg(target_os = "macos")]
fn listens_on(port: u16, pid: u32) -> Option<bool> {
    let output = Command::new("/usr/sbin/lsof")
        .args(["-nP", "-a", "-p", &pid.to_string()])
        .arg(format!("-iTCP@127.0.0.1:{port}"))
        .args(["-sTCP:LISTEN", "-Fp"])
        .stdin(Stdio::null())
        .output()
        .ok()?;
    let me = format!("p{pid}");
    if String::from_utf8_lossy(&output.stdout)
        .lines()
        .any(|l| l == me)
    {
        return Some(true);
    }
    // `lsof` exits 1 and says nothing when the process simply holds no such socket; anything else is unknown.
    (output.status.code() == Some(1) && output.stdout.is_empty() && output.stderr.is_empty())
        .then_some(false)
}

/// Linux: the listener's socket inode from `/proc/net/tcp`, looked for among `pid`'s own descriptors.
#[cfg(target_os = "linux")]
fn listens_on(port: u16, pid: u32) -> Option<bool> {
    let table = fs::read_to_string("/proc/net/tcp").ok()?;
    let local = format!("0100007F:{port:04X}");
    let inode = table.lines().skip(1).find_map(|row| {
        let cols: Vec<&str> = row.split_whitespace().collect();
        (cols.get(1) == Some(&local.as_str()) && cols.get(3) == Some(&"0A"))
            .then(|| cols.get(9).map(|s| s.to_string()))
            .flatten()
    })?;
    let socket = format!("socket:[{inode}]");
    let fds = fs::read_dir(format!("/proc/{pid}/fd")).ok()?;
    Some(
        fds.flatten()
            .any(|fd| fs::read_link(fd.path()).is_ok_and(|t| t.as_os_str() == socket.as_str())),
    )
}

/// Windows: the owning PIDs `netstat -ano` lists for listeners on the port.
#[cfg(windows)]
fn listens_on(port: u16, pid: u32) -> Option<bool> {
    let output = Command::new("netstat")
        .args(["-ano", "-p", "TCP"])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&output.stdout).into_owned();
    let addresses = [format!("127.0.0.1:{port}"), format!("0.0.0.0:{port}")];
    let owners: Vec<u32> = text
        .lines()
        .filter_map(|row| {
            let cols: Vec<&str> = row.split_whitespace().collect();
            (cols.len() == 5 && addresses.iter().any(|a| a == cols[1]) && cols[3] == "LISTENING")
                .then(|| cols[4].parse().ok())
                .flatten()
        })
        .collect();
    (!owners.is_empty()).then(|| owners.contains(&pid))
}

#[cfg(not(any(target_os = "macos", target_os = "linux", windows)))]
fn listens_on(_: u16, _: u32) -> Option<bool> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plan(epoch: &str) -> String {
        format!(
            "{{\"plan_version\":1,\"epoch\":\"{epoch}\",\"model\":null,\"reason\":\"no_model_manifest\",\
             \"attempts\":[],\"restart\":{{\"backoff_s\":[1,2,4],\"max_restarts\":3,\"window_s\":300}}}}"
        )
    }

    #[test]
    fn plans_from_another_core_are_ignored() {
        let dir = std::env::temp_dir().join(format!("jana-plan-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("launch.json");
        fs::write(&path, plan("0123456789abcdef")).unwrap();
        let read = read_plan(&path, "0123456789abcdef").unwrap();
        assert_eq!(read.model, None);
        assert_eq!(read.reason.as_deref(), Some("no_model_manifest"));
        assert_eq!(read.restart.backoff_s, vec![1.0, 2.0, 4.0]);
        assert_eq!(
            read_plan(&path, "fedcba9876543210").unwrap_err(),
            "stale_plan"
        );
        assert_eq!(
            read_plan(&dir.join("missing.json"), "x").unwrap_err(),
            "no_plan"
        );
    }

    fn args_of(cmd: &Command) -> Vec<String> {
        cmd.get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect()
    }

    #[test]
    fn runtime_yields_to_the_app() {
        let command = RuntimeCommand {
            program: PathBuf::from("/opt/jana/llama-server"),
            prefix_args: vec![],
        };
        let attempt = Attempt {
            model: "m".into(),
            args: vec!["--ctx-size".into(), "6144".into()],
        };
        let priority = Priority {
            niceness: 10,
            reserved_cores: 1,
        };
        let key = Path::new("/tmp/key");
        // Below normal priority through `nice`, and threads capped at the physical cores minus one.
        let cmd = runtime_command(
            &command,
            &attempt,
            4000,
            key,
            Some(&priority),
            Some(8),
            Some(Path::new("/usr/bin/nice")),
        );
        assert_eq!(cmd.get_program(), "/usr/bin/nice");
        let args = args_of(&cmd);
        assert_eq!(&args[..3], ["-n", "10", "/opt/jana/llama-server"]);
        assert_eq!(&args[args.len() - 2..], ["--threads", "7"]);
        assert!(args.windows(2).any(|w| w == ["--port", "4000"]));
        // At least one thread; no cap when the core count is unknown or the plan predates ARC-31.
        assert_eq!(runtime_threads(Some(&priority), Some(1)), Some(1));
        assert_eq!(runtime_threads(Some(&priority), None), None);
        assert_eq!(runtime_threads(None, Some(8)), None);
        let plain = runtime_command(&command, &attempt, 4000, key, None, Some(8), None);
        assert_eq!(plain.get_program(), "/opt/jana/llama-server");
        assert!(!args_of(&plain).contains(&"--threads".to_string()));
        // The plan's own thread count wins.
        let pinned = Attempt {
            model: "m".into(),
            args: vec!["--threads".into(), "2".into()],
        };
        let cmd = runtime_command(&command, &pinned, 4000, key, Some(&priority), Some(8), None);
        assert_eq!(
            args_of(&cmd).iter().filter(|a| *a == "--threads").count(),
            1
        );
    }

    #[test]
    fn plans_carry_the_priority() {
        let with: Plan = serde_json::from_str(
            "{\"plan_version\":1,\"epoch\":\"e\",\"model\":null,\"restart\":{\"backoff_s\":[1],\
             \"max_restarts\":3,\"window_s\":300},\"priority\":{\"niceness\":10,\"reserved_cores\":1}}",
        )
        .unwrap();
        assert_eq!(
            with.priority,
            Some(Priority {
                niceness: 10,
                reserved_cores: 1
            })
        );
        let without: Plan = serde_json::from_str(&plan("e")).unwrap();
        assert_eq!(without.priority, None);
    }

    /// SEC-24 / API-02: a process that takes the launch's port before the runtime binds it is recognised, so the
    /// endpoint and key never go to it; the process that does hold the listener is recognised as the runtime.
    #[cfg(any(target_os = "macos", target_os = "linux"))]
    #[test]
    fn port_squatter_is_never_taken_for_the_runtime() {
        let squatter = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = squatter.local_addr().unwrap().port();
        let mut runtime = Command::new("sleep").arg("30").spawn().unwrap();
        assert!(port_held_by_another(port, runtime.id()));
        assert!(!port_held_by_another(port, std::process::id()));
        let _ = runtime.kill();
        let _ = runtime.wait();
    }

    /// A runtime's stderr is drained as it is written and only its last lines are kept (OBS-16).
    #[cfg(unix)]
    #[test]
    fn stderr_tail_keeps_the_last_lines() {
        let mut child = Command::new("sh")
            .args([
                "-c",
                "i=0; while [ $i -lt 50 ]; do echo line $i >&2; i=$((i+1)); done",
            ])
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let tail = StderrTail::follow(child.stderr.take(), 10);
        child.wait().unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while tail.lines().last().map(String::as_str) != Some("line 49")
            && Instant::now() < deadline
        {
            thread::sleep(Duration::from_millis(10));
        }
        let lines = tail.lines();
        assert_eq!(lines.len(), 10);
        assert_eq!(lines[0], "line 40");
    }

    /// A synthetic distress sentence a runtime echoes on stderr never reaches the crash tail; diagnostics do.
    #[cfg(unix)]
    #[test]
    fn stderr_tail_withholds_content() {
        let script = "echo 'llama_model_load: loaded meta data with 33 key-value pairs' >&2; \
                      echo 'prompt: I want to hurt myself and I cannot do this anymore' >&2; \
                      echo 'slot launch_slot_: id 0 | task 12 | processing task' >&2; \
                      echo 'GGML_ASSERT(ctx) failed' >&2";
        let mut child = Command::new("sh")
            .args(["-c", script])
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let tail = StderrTail::follow(child.stderr.take(), 10);
        child.wait().unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while tail.lines().len() < 4 && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        let lines = tail.lines();
        assert_eq!(
            lines,
            [
                "llama_model_load: loaded meta data with 33 key-value pairs",
                "[withheld 1 line]",
                "slot launch_slot_: id 0 | task 12 | processing task",
                "GGML_ASSERT(ctx) failed",
            ]
        );
        assert!(!lines.join("\n").contains("hurt myself"));
    }

    /// The core's stderr reaches the shell's own as diagnostic lines only: a traceback's frames and type pass, a
    /// synthetic distress sentence (a message, an echoed request body) never does (OBS-19).
    #[cfg(unix)]
    #[test]
    fn core_stderr_is_forwarded_as_diagnostics_only() {
        #[derive(Clone, Default)]
        struct Sink(Arc<Mutex<Vec<u8>>>);
        impl Write for Sink {
            fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
                self.0.lock().unwrap().extend_from_slice(buf);
                Ok(buf.len())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let script = "echo 'Traceback (most recent call last):' >&2; \
                      echo '  at agent_core/api/app.py:120 in run' >&2; \
                      echo 'ValueError: I want to hurt myself' >&2; \
                      echo 'body {\"text\": \"I want to hurt myself\"}' >&2";
        let mut child = Command::new("sh")
            .args(["-c", script])
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let sink = Sink::default();
        let reader = forward_diagnostics_to(child.stderr.take().unwrap(), sink.clone());
        child.wait().unwrap();
        reader.join().unwrap();
        let out = String::from_utf8(sink.0.lock().unwrap().clone()).unwrap();
        assert_eq!(
            out,
            "Traceback (most recent call last):\n  at agent_core/api/app.py:120 in run\n[withheld 2 lines]\n"
        );
    }

    #[test]
    fn diagnostic_lines_match_the_core() {
        assert!(diagnostic(
            "main: server is listening on http://127.0.0.1:8080"
        ));
        assert!(diagnostic("Traceback (most recent call last):"));
        assert!(!diagnostic("I want to hurt myself"));
        assert!(!diagnostic("WANT TO DIE"));
        assert!(!diagnostic(
            "my answer is x = 3 because the teacher said so"
        ));
        assert_eq!(
            diagnostic_lines(["a", "please help", "me", "done"]),
            ["a", "[withheld 2 lines]", "done"]
        );
    }

    #[test]
    fn key_file_is_private() {
        let dir = std::env::temp_dir().join(format!("jana-key-{}", std::process::id()));
        let path = dir.join("key");
        write_key(&path, "secret").unwrap();
        write_key(&path, "another").unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "another");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }
}
