//! Starting and supervising the agent core (ARC-02, ARC-04, ARC-22 to ARC-24).
//!
//! The shell spawns the core in its own process tree (a process group on Unix, a kill-on-close job object on
//! Windows), sends hello, the device secrets from its key store (`control.keys`, SEC-17), config, the launch token
//! and the OS network hint (`control.net_state`, ARC-08) over stdin and waits for `control.ready` with the loopback
//! port. It answers the core's key requests in order and sends the network hint again whenever it changes. A crash
//! restarts it after the configured backoff with a new token (the new process also has a new epoch, so the UI
//! reloads its snapshot); too many crashes inside the window give up. On quit the shell asks the core to shut
//! down, lets it finish its own steps while leaving the runtime its step, then ends the whole tree, so no product
//! process outlives the total deadline.

use crate::control::{
    self, Config, Hello, NetState, Readiness, Ready, Redacted, Secret, SecretName, Shutdown,
    ToCore, ToShell, UpdateInstall, VoiceStop,
};
use crate::generated::keys;
use crate::keychain::KeyStore;
use crate::launch::Token;
use crate::orphans;
use crate::process_tree::{self, Started};
use crate::runtime::CoreLink;
use serde::Serialize;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct CoreCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub config: Config,
    /// The core's device secrets (SEC-17, D97).
    pub keys: Arc<KeyStore>,
    /// The OS reachability hint (ARC-08), asked at each start and on the hint poll interval.
    pub net_hint: fn() -> bool,
}

/// The pilot deployment's signed country file (PRD-22): `config/pilot-country.json` in the app's resources, passed
/// to the core as `control.config.pilot_country_file` only when a pilot build ships it.
pub fn pilot_country_file(resources: &std::path::Path) -> Option<String> {
    let path = resources.join(PILOT_COUNTRY_FILE);
    path.is_file().then(|| path.display().to_string())
}

/// Where a pilot build carries its country file, relative to the resources folder.
pub const PILOT_COUNTRY_FILE: &str = "config/pilot-country.json";

#[derive(Debug, Clone)]
pub struct Policy {
    pub backoff: Vec<Duration>,
    pub max_crashes: usize,
    pub window: Duration,
    pub step_deadline: Duration,
    pub total_deadline: Duration,
}

impl Default for Policy {
    /// The configured policy (ARC-24 restart policy, ARC-23 deadlines), from the declared configuration keys.
    fn default() -> Self {
        Policy {
            backoff: keys::CORE_RESTART_BACKOFF_S
                .iter()
                .map(|s| Duration::from_secs_f64(*s))
                .collect(),
            max_crashes: keys::CORE_RESTART_MAX,
            window: Duration::from_secs_f64(keys::CORE_RESTART_WINDOW_S),
            step_deadline: Duration::from_secs_f64(keys::SHUTDOWN_GRACE_S),
            total_deadline: Duration::from_secs_f64(keys::SHUTDOWN_TOTAL_S),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum State {
    Starting,
    Ready {
        port: u16,
        epoch: String,
    },
    Restarting {
        attempt: usize,
    },
    GaveUp,
    /// The core speaks another control-channel major (ARC-29): no restart; the app shows "Please reinstall".
    Incompatible,
    Stopped,
}

/// What the webview needs to reach the core (API-02): kept in memory, handed over by a command.
#[derive(Debug, Clone, Serialize)]
pub struct LaunchInfo {
    pub base_url: String,
    pub token: String,
}

struct Shared {
    state: State,
    token: Token,
    pid: Option<u32>,
    /// The running core process and its tree, for a quit that has to end it.
    process: Option<Arc<Started>>,
    stdin: Option<ChildStdin>,
    stop: bool,
    restarts: usize,
    readiness: String,
    incompatible: bool,
    downloads: Vec<ToShell>,
    exit_requested: bool,
    update_install: Option<UpdateInstall>,
    /// The network hint the running core was last sent.
    net_online: Option<bool>,
}

pub struct Supervisor {
    shared: Arc<(Mutex<Shared>, Condvar)>,
    policy: Policy,
    thread: Mutex<Option<JoinHandle<()>>>,
    network: Mutex<Option<JoinHandle<()>>>,
}

fn lock(shared: &(Mutex<Shared>, Condvar)) -> MutexGuard<'_, Shared> {
    shared
        .0
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

impl Supervisor {
    /// Start the core and keep it running. Orphans recorded by a previous run are ended first (ARC-24).
    pub fn start(command: CoreCommand, policy: Policy, pid_file: Option<PathBuf>) -> Supervisor {
        if let Some(path) = &pid_file {
            orphans::recover(path);
        }
        let shared = Arc::new((
            Mutex::new(Shared {
                state: State::Starting,
                token: Token::new(),
                pid: None,
                process: None,
                stdin: None,
                stop: false,
                restarts: 0,
                readiness: "starting".into(),
                incompatible: false,
                downloads: vec![],
                exit_requested: false,
                update_install: None,
                net_online: None,
            }),
            Condvar::new(),
        ));
        let network = {
            let shared = Arc::clone(&shared);
            let hint = command.net_hint;
            thread::spawn(move || watch_network(&shared, hint))
        };
        let worker = {
            let shared = Arc::clone(&shared);
            let policy = policy.clone();
            thread::spawn(move || run(&shared, &command, &policy, pid_file.as_deref()))
        };
        Supervisor {
            shared,
            policy,
            thread: Mutex::new(Some(worker)),
            network: Mutex::new(Some(network)),
        }
    }

    pub fn state(&self) -> State {
        lock(&self.shared).state.clone()
    }

    pub fn pid(&self) -> Option<u32> {
        lock(&self.shared).pid
    }

    pub fn restarts(&self) -> usize {
        lock(&self.shared).restarts
    }

    pub fn readiness(&self) -> String {
        lock(&self.shared).readiness.clone()
    }

    pub fn take_downloads(&self) -> Vec<ToShell> {
        std::mem::take(&mut lock(&self.shared).downloads)
    }

    pub fn take_exit_requested(&self) -> bool {
        std::mem::take(&mut lock(&self.shared).exit_requested)
    }

    pub fn take_update_install(&self) -> Option<UpdateInstall> {
        lock(&self.shared).update_install.take()
    }

    /// The core's address and token once it is ready, waiting up to `timeout`.
    pub fn launch_info(&self, timeout: Duration) -> Option<LaunchInfo> {
        let deadline = Instant::now() + timeout;
        let mut guard = lock(&self.shared);
        loop {
            match &guard.state {
                State::Ready { port, .. } => {
                    return Some(LaunchInfo {
                        base_url: format!("http://127.0.0.1:{port}"),
                        token: guard.token.reveal().to_string(),
                    });
                }
                State::GaveUp | State::Incompatible | State::Stopped => return None,
                _ => {}
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return None;
            }
            guard = self
                .shared
                .1
                .wait_timeout(guard, left)
                .map(|(g, _)| g)
                .unwrap_or_else(|e| e.into_inner().0);
        }
    }

    /// Send a control message to the running core (for example the runtime endpoint).
    pub fn send(&self, message: &ToCore) -> bool {
        let mut guard = lock(&self.shared);
        match guard.stdin.as_mut() {
            Some(stdin) => stdin
                .write_all(control::line(message).as_bytes())
                .and_then(|()| stdin.flush())
                .is_ok(),
            None => false,
        }
    }

    /// Quit (ARC-23): ask the core to stop, giving running turns the step deadline, then wait for it to finish its
    /// own steps (ending turns, flushing, stopping the worker and, when an update installs at quit, the learner
    /// snapshot) until one step deadline is left of the total for the runtime; then end its tree. Returns how long it
    /// took, never more than the total deadline.
    pub fn shutdown(&self) -> Duration {
        let started = Instant::now();
        let process = {
            let mut guard = lock(&self.shared);
            guard.stop = true;
            if let Some(stdin) = guard.stdin.as_mut() {
                let grace_ms = self.policy.step_deadline.as_millis().min(5000) as u16;
                let shutdown = ToCore::Shutdown(Shutdown {
                    grace_ms: Some(grace_ms),
                });
                let _ = stdin.write_all(control::line(&shutdown).as_bytes());
                let _ = stdin.flush();
            }
            self.shared.1.notify_all();
            guard.process.clone()
        };
        let core_steps = self
            .policy
            .total_deadline
            .saturating_sub(self.policy.step_deadline)
            .max(self.policy.step_deadline);
        let mut stopped = self.wait_stopped(core_steps);
        if !stopped {
            if let Some(process) = process {
                process.kill(); // a kill, then the process itself: nothing below waits on a live core
            }
            let left = self.policy.total_deadline.saturating_sub(started.elapsed());
            stopped = self.wait_stopped(left);
        }
        if let Some(handle) = self
            .network
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .take()
        {
            let _ = handle.join(); // it wakes on `stop`
        }
        // A thread still reading a pipe some escaped process holds open is left behind rather than waited on.
        if stopped
            && let Some(handle) = self.thread.lock().unwrap_or_else(|e| e.into_inner()).take()
        {
            let _ = handle.join();
        }
        started.elapsed()
    }

    fn wait_stopped(&self, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        let mut guard = lock(&self.shared);
        while !matches!(
            guard.state,
            State::Stopped | State::GaveUp | State::Incompatible
        ) {
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
}

/// The runtime supervisor reaches the core through this supervisor: the endpoint goes to whichever core process is
/// ready, and a restarted core is sent it again (MDL-19).
impl CoreLink for Supervisor {
    fn ready_epoch(&self) -> Option<String> {
        match &lock(&self.shared).state {
            State::Ready { epoch, .. } => Some(epoch.clone()),
            _ => None,
        }
    }

    fn send(&self, message: &ToCore) -> bool {
        Supervisor::send(self, message)
    }

    fn readiness(&self) -> Option<String> {
        Some(Supervisor::readiness(self))
    }
}

fn set_state(shared: &(Mutex<Shared>, Condvar), state: State) {
    lock(shared).state = state;
    shared.1.notify_all();
}

/// Send the running core the OS network hint whenever it changes (ARC-08), until the supervisor stops.
fn watch_network(shared: &Arc<(Mutex<Shared>, Condvar)>, hint: fn() -> bool) {
    let interval = Duration::from_millis(keys::NET_OS_HINT_POLL_MS as u64);
    loop {
        {
            let guard = lock(shared);
            let (guard, _) = shared
                .1
                .wait_timeout_while(guard, interval, |s| !s.stop)
                .unwrap_or_else(|e| e.into_inner());
            if guard.stop {
                return;
            }
        }
        let online = hint();
        let mut guard = lock(shared);
        if guard.net_online.is_some_and(|sent| sent != online)
            && let Some(stdin) = guard.stdin.as_mut()
        {
            let frame = ToCore::NetState(NetState { online });
            if stdin
                .write_all(control::line(&frame).as_bytes())
                .and_then(|()| stdin.flush())
                .is_ok()
            {
                guard.net_online = Some(online);
            }
        }
    }
}

/// Write one frame to the running core `pid`, if it is still the one running.
fn reply(shared: &(Mutex<Shared>, Condvar), pid: u32, message: &ToCore) {
    let mut guard = lock(shared);
    if guard.pid == Some(pid)
        && let Some(stdin) = guard.stdin.as_mut()
    {
        let _ = stdin.write_all(control::line(message).as_bytes());
        let _ = stdin.flush();
    }
}

fn spawn(command: &CoreCommand) -> std::io::Result<Child> {
    let mut cmd = Command::new(&command.program);
    cmd.args(&command.args)
        .current_dir(&command.cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped()); // passed on as diagnostic lines only (OBS-19): never a request body or an answer
    process_tree::isolate(&mut cmd); // quitting ends the core and every process it started
    let mut child = cmd.spawn()?;
    crate::runtime::forward_diagnostics(child.stderr.take());
    Ok(child)
}

fn run(
    shared: &Arc<(Mutex<Shared>, Condvar)>,
    command: &CoreCommand,
    policy: &Policy,
    pid_file: Option<&std::path::Path>,
) {
    let mut crashes: Vec<Instant> = Vec::new();
    loop {
        if lock(shared).stop {
            set_state(shared, State::Stopped);
            return;
        }
        let token = Token::new();
        let mut child = match spawn(command) {
            Ok(child) => child,
            Err(_) => {
                set_state(shared, State::GaveUp);
                return;
            }
        };
        let pid = child.id();
        if let Some(path) = pid_file {
            orphans::track(path, pid);
        }
        let mut stdin = child.stdin.take();
        // SEC-17: the device secrets go before the config, so the core starts on them; ARC-08: the network hint
        // once the core has what it needs to start.
        let online = (command.net_hint)();
        if let Some(stdin) = stdin.as_mut() {
            for message in [
                ToCore::Hello(Hello {
                    protocol: control::CONTROL_PROTOCOL,
                    shell_version: None,
                }),
                command.keys.keys_frame(),
                ToCore::Config(command.config.clone()),
                ToCore::Secret(Secret {
                    name: SecretName::LaunchToken,
                    profile_id: None,
                    value: Redacted::new(token.reveal()),
                }),
                ToCore::NetState(NetState { online }),
            ] {
                let _ = stdin.write_all(control::line(&message).as_bytes());
            }
            let _ = stdin.flush();
        }
        let stdout = child.stdout.take();
        let process = Arc::new(Started::new(child));
        {
            let mut guard = lock(shared);
            guard.token = token;
            guard.pid = Some(pid);
            guard.process = Some(process.clone());
            guard.stdin = stdin;
            guard.net_online = Some(online);
            guard.state = State::Starting;
            shared.1.notify_all();
        }
        let mut voice: Option<crate::voice::VoiceSupervisor> = None;
        if let Some(stdout) = stdout {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                let frame = control::parse(&line);
                if let Some(answer) = frame.as_ref().and_then(|f| command.keys.answer(f)) {
                    reply(shared, pid, &answer); // control.key_result, in the order asked (SEC-17)
                    continue;
                }
                match frame {
                    Some(ToShell::VoiceStart(launch)) => {
                        drop(voice.take());
                        let channel = Arc::clone(shared);
                        let pid_file =
                            PathBuf::from(&command.config.data_dir).join("runtime/voice-pid.json");
                        voice = Some(crate::voice::VoiceSupervisor::start(
                            launch,
                            pid_file,
                            move |message| {
                                if !lock(&channel).stop {
                                    reply(&channel, pid, &message);
                                }
                            },
                        ));
                    }
                    Some(ToShell::VoiceStop(VoiceStop { request_id })) => {
                        if voice
                            .as_ref()
                            .is_some_and(|worker| worker.matches(&request_id))
                        {
                            drop(voice.take());
                        }
                    }
                    Some(ToShell::Error(error)) if error.code == "protocol_mismatch" => {
                        lock(shared).incompatible = true;
                    }
                    Some(ToShell::Ready(Ready {
                        api_port, epoch, ..
                    })) => {
                        crate::crash::set_epoch(&epoch); // a shell crash names the core it was serving (OBS-16)
                        set_state(
                            shared,
                            State::Ready {
                                port: api_port,
                                epoch,
                            },
                        )
                    }
                    Some(ToShell::Readiness(Readiness { readiness, .. })) => {
                        lock(shared).readiness = readiness.as_str().to_string();
                        shared.1.notify_all();
                    }
                    Some(ToShell::ExitRequested(_)) => lock(shared).exit_requested = true,
                    Some(ToShell::UpdateInstall(plan)) => {
                        // A crashed core may not enqueue an installer while it is being automatically restarted.
                        if lock(shared).stop {
                            lock(shared).update_install = Some(plan);
                        }
                    }
                    Some(message @ (ToShell::Download(_) | ToShell::DownloadControl(_))) => {
                        lock(shared).downloads.push(message);
                    }
                    Some(
                        ToShell::Bye(_)
                        | ToShell::Error(_)
                        | ToShell::KeyPut(_)
                        | ToShell::KeyDelete(_),
                    )
                    | None => {}
                }
            }
        }
        drop(voice); // a stopped or crashed core never leaves its speech process behind
        process.wait();
        {
            let mut guard = lock(shared);
            guard.stdin = None;
            guard.net_online = None;
            guard.pid = None;
            guard.process = None;
            if guard.incompatible {
                guard.state = State::Incompatible;
                shared.1.notify_all();
                return;
            }
            if guard.stop {
                guard.state = State::Stopped;
                shared.1.notify_all();
                if let Some(path) = pid_file {
                    let _ = std::fs::remove_file(path);
                }
                return;
            }
        }
        // A crash: restart after the backoff, or give up after too many inside the window (ARC-24).
        let now = Instant::now();
        crashes.retain(|t| now.duration_since(*t) < policy.window);
        crashes.push(now);
        if crashes.len() >= policy.max_crashes {
            set_state(shared, State::GaveUp);
            return;
        }
        let attempt = crashes.len() - 1;
        set_state(shared, State::Restarting { attempt });
        let wait = policy
            .backoff
            .get(attempt)
            .or(policy.backoff.last())
            .copied()
            .unwrap_or_default();
        let guard = lock(shared);
        let (mut guard, _) = shared
            .1
            .wait_timeout_while(guard, wait, |s| !s.stop)
            .unwrap_or_else(|e| e.into_inner());
        guard.restarts += 1;
    }
}
