//! The shell's supervision against the real agent core sidecar (ARC-02, ARC-04, ARC-23, ARC-24, MDL-19) and its
//! webview hardening (SEC-11). Headless: the supervisors are the code the Tauri app runs; no window is needed. The
//! model runtime is the repository's fake llama-server process over synthetic model files; no real model runs.

use jana_shell::control::Config;
use jana_shell::keychain::KeyStore;
use jana_shell::orphans::{self, Record};
use jana_shell::runtime::{
    CoreLink, RuntimeCommand, RuntimePolicy, RuntimeState, RuntimeSupervisor,
};
use jana_shell::supervisor::{CoreCommand, Policy, State, Supervisor};
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::thread::sleep;
use std::time::{Duration, Instant};
use sysinfo::{Pid, ProcessRefreshKind, ProcessesToUpdate, System, UpdateKind};

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

/// The repository's virtual environment's Python (`uv sync`) on this OS.
fn python() -> PathBuf {
    if cfg!(windows) {
        repo().join(".venv/Scripts/python.exe")
    } else {
        repo().join(".venv/bin/python")
    }
}

/// End a process at once, as a crash would: SIGKILL, or TerminateProcess on Windows.
fn kill_now(pid: u32) {
    let pid = pid.to_string();
    let _ = if cfg!(windows) {
        Command::new("taskkill").args(["/F", "/PID", &pid]).status()
    } else {
        Command::new("kill").args(["-9", &pid]).status()
    };
}

fn core(data: &std::path::Path) -> CoreCommand {
    let repo = repo();
    CoreCommand {
        program: python(),
        args: vec!["-m".into(), "agent_core.api".into()],
        cwd: repo.clone(),
        config: Config {
            data_dir: data.display().to_string(),
            content_root: repo.join("content/agent").display().to_string(),
            skills_root: repo.join("skills").display().to_string(),
            release: false,
            dev_origins: None,
            scripted: Some(true),
            pilot_country_file: None,
        },
        // The SEC-17 file fallback in a folder of its own beside the data folder: tests never touch a keychain.
        keys: Arc::new(KeyStore::files(data.with_extension("keys"), data).unwrap()),
        net_hint: || false,
    }
}

/// A core that runs the model runtime (not the scripted provider), with `models` synthetic models installed, and the
/// runtime supervisor started on the fake llama-server.
fn core_with_runtime(name: &str, models: usize) -> (Arc<Supervisor>, RuntimeSupervisor, PathBuf) {
    let data = scratch(name);
    let installed = Command::new(python())
        .args(["-m", "jana_tools.fakes.models"])
        .arg(&data)
        .arg(models.to_string())
        .status()
        .unwrap();
    assert!(installed.success());
    let mut command = core(&data);
    command.config.scripted = None;
    let core = Arc::new(Supervisor::start(command, Policy::default(), None));
    let link: Arc<dyn CoreLink> = core.clone();
    let runtime = RuntimeSupervisor::start(
        link,
        data.join("runtime/launch.json"),
        RuntimeCommand {
            program: python(),
            prefix_args: vec!["-m".into(), "jana_tools.fakes.llama_server".into()],
        },
        RuntimePolicy::default(),
        Some(data.join("runtime-pids.json")),
    );
    (core, runtime, data)
}

/// Whether the core planned a runtime. It plans none on a computer below the minimum laptop (PLT-29), whose probe it
/// reads: there the runtime-dependent checks cannot run, and content-only is the right outcome.
fn plans_runtime(core: &Supervisor, runtime: &RuntimeSupervisor, data: &std::path::Path) -> bool {
    core.launch_info(Duration::from_secs(60))
        .expect("the core reports ready");
    let plan: serde_json::Value =
        serde_json::from_slice(&std::fs::read(data.join("runtime/launch.json")).unwrap()).unwrap();
    if plan["model"].is_null() {
        assert_eq!(plan["reason"], "content_only_class", "{plan}");
        assert!(runtime.wait_for(Duration::from_secs(10), |s| matches!(
            s,
            RuntimeState::NoModel { .. }
        )));
        eprintln!(
            "this computer is below the minimum laptop: content-only, no runtime to supervise"
        );
        return false;
    }
    true
}

fn wait_readiness(core: &Supervisor, want: &str, seconds: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while core.readiness() != want && Instant::now() < deadline {
        sleep(Duration::from_millis(20));
    }
    core.readiness() == want
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("jana-shell-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let _ = std::fs::remove_dir_all(dir.with_extension("keys"));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn system() -> System {
    let mut system = System::new();
    system.refresh_processes_specifics(
        ProcessesToUpdate::All,
        true,
        ProcessRefreshKind::nothing()
            .with_exe(UpdateKind::Always)
            .with_cmd(UpdateKind::Always)
            .with_environ(UpdateKind::Always),
    );
    system
}

/// The process and everything it started.
fn tree(root: u32) -> Vec<(u32, String)> {
    let system = system();
    let mut out = vec![];
    let mut frontier = vec![Pid::from_u32(root)];
    while let Some(pid) = frontier.pop() {
        if let Some(process) = system.process(pid) {
            out.push((
                pid.as_u32(),
                process
                    .cmd()
                    .iter()
                    .map(|s| s.to_string_lossy())
                    .collect::<Vec<_>>()
                    .join(" "),
            ));
        }
        for (child, process) in system.processes() {
            // Linux lists threads as tasks of a process; only processes count.
            if process.parent() == Some(pid) && process.thread_kind().is_none() {
                frontier.push(*child);
            }
        }
    }
    out
}

fn alive(pid: u32) -> bool {
    let system = system();
    system.process(Pid::from_u32(pid)).is_some_and(|p| {
        !matches!(
            p.status(),
            sysinfo::ProcessStatus::Zombie | sysinfo::ProcessStatus::Dead
        )
    })
}

#[test]
fn arc02_process_tree_matches_table() {
    let (sup, runtime, data) = core_with_runtime("tree", 2);
    let info = sup
        .launch_info(Duration::from_secs(60))
        .expect("the core reports ready");
    assert!(info.base_url.starts_with("http://127.0.0.1:"));
    // The shell, not the core, started the model runtime: its own child, on the verified models folder, with the
    // model the core planned; the core reports ready only after its touch generation (MDL-20).
    if plans_runtime(&sup, &runtime, &data) {
        assert!(wait_readiness(&sup, "ready", 60), "{}", sup.readiness());
        assert!(
            matches!(runtime.state(), RuntimeState::Running { ref model, .. } if model == "synthetic-large")
        );
        let runtime_pid = runtime.pid().unwrap();
        let system = system();
        let process = system.process(Pid::from_u32(runtime_pid)).unwrap();
        assert_eq!(
            process.parent().map(|p| p.as_u32()),
            Some(std::process::id())
        );
        let argv = process
            .cmd()
            .iter()
            .map(|s| s.to_string_lossy())
            .collect::<Vec<_>>()
            .join(" ");
        let models_dir = data.join("runtime/models").display().to_string();
        assert!(
            argv.contains(&format!("--models-dir {models_dir}")),
            "{argv}"
        );
        assert!(
            !tree(sup.pid().unwrap())
                .iter()
                .any(|(p, _)| *p == runtime_pid)
        );
    }
    sleep(Duration::from_millis(500));
    let pid = sup.pid().unwrap();
    let processes = tree(pid);
    let core: Vec<_> = processes
        .iter()
        .filter(|(_, cmd)| cmd.contains("agent_core.api"))
        .collect();
    let workers: Vec<_> = processes
        .iter()
        .filter(|(_, cmd)| cmd.contains("tool_worker"))
        .collect();
    // The shell started exactly one core; the core (not the shell) started the sandboxed tool worker; nothing else
    // runs under the core.
    assert_eq!(core.len(), 1, "{processes:?}");
    assert!(!workers.is_empty(), "{processes:?}");
    let unexpected: Vec<_> = processes
        .iter()
        .filter(|(_, cmd)| {
            !cmd.contains("agent_core.api")
                && !cmd.contains("tool_worker")
                && !cmd.contains("sandbox-exec")
                && !cmd.contains("bwrap")
        })
        .collect();
    assert!(unexpected.is_empty(), "{unexpected:?}");
    sup.shutdown();
    runtime.shutdown(Duration::from_secs(3));
    assert!(runtime.pid().is_none());
}

/// SEC-17 and D97 with the real core: the device secret it creates reaches the shell's key store (`control.key_put`)
/// as a private file outside the data folder, and the next start hands it back (`control.keys`), so the core keeps
/// using the same secret instead of making a new one.
#[test]
fn core_device_secrets_live_in_the_shell_key_store() {
    let data = scratch("keys");
    let keys = data.with_extension("keys");
    let secret = keys.join("jana.device-db");
    let sup = Supervisor::start(core(&data), Policy::default(), None);
    sup.launch_info(Duration::from_secs(60)).expect("ready");
    let deadline = Instant::now() + Duration::from_secs(20);
    while !secret.is_file() && Instant::now() < deadline {
        sleep(Duration::from_millis(20));
    }
    let first = std::fs::read(&secret).expect("the core stored its device secret with the shell");
    sup.shutdown();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&secret).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
    }
    let sup = Supervisor::start(core(&data), Policy::default(), None);
    sup.launch_info(Duration::from_secs(60)).expect("ready");
    sleep(Duration::from_millis(500));
    sup.shutdown();
    assert_eq!(std::fs::read(&secret).unwrap(), first);
}

#[test]
fn arc23_no_orphans_after_quit() {
    let data = scratch("quit");
    let sup = Supervisor::start(core(&data), Policy::default(), Some(data.join("pids.json")));
    sup.launch_info(Duration::from_secs(60)).expect("ready");
    sleep(Duration::from_millis(500));
    let started: Vec<u32> = tree(sup.pid().unwrap())
        .into_iter()
        .map(|(p, _)| p)
        .collect();
    assert!(started.len() >= 2);
    let took = sup.shutdown();
    let policy = Policy::default();
    assert!(took <= policy.total_deadline, "{took:?}");
    // With the model runtime: the core first, then the runtime, all inside the total deadline.
    let (with_runtime, runtime, data) = core_with_runtime("quit-runtime", 1);
    if !plans_runtime(&with_runtime, &runtime, &data) {
        with_runtime.shutdown();
        runtime.shutdown(Duration::from_secs(1));
        return;
    }
    assert!(wait_readiness(&with_runtime, "ready", 60));
    let mut everything: Vec<u32> = tree(with_runtime.pid().unwrap())
        .into_iter()
        .map(|(p, _)| p)
        .collect();
    everything.push(runtime.pid().unwrap());
    let quitting = Instant::now();
    with_runtime.shutdown();
    runtime.shutdown(policy.total_deadline.saturating_sub(quitting.elapsed()));
    assert!(quitting.elapsed() <= policy.total_deadline);
    sleep(Duration::from_millis(300));
    let left: Vec<u32> = everything.into_iter().filter(|p| alive(*p)).collect();
    assert!(left.is_empty(), "still running: {left:?}");
    sleep(Duration::from_millis(300));
    let left: Vec<u32> = started.into_iter().filter(|p| alive(*p)).collect();
    assert!(left.is_empty(), "still running: {left:?}");
    assert_eq!(sup.state(), State::Stopped);
    assert!(!data.join("pids.json").exists());
}

#[test]
fn arc24_restart_policy_per_process() {
    let data = scratch("restart");
    let policy = Policy {
        backoff: vec![Duration::from_millis(100), Duration::from_millis(200)],
        max_crashes: 3,
        window: Duration::from_secs(120),
        ..Policy::default()
    };
    let sup = Supervisor::start(core(&data), policy, None);
    let first = sup.launch_info(Duration::from_secs(60)).expect("ready");
    // A crash: the core restarts after the backoff, on a new port with a new token (the UI re-acquires both).
    let crash = |sup: &Supervisor| {
        let pid = sup.pid().expect("running");
        kill_now(pid);
        let deadline = Instant::now() + Duration::from_secs(10);
        while sup.pid() == Some(pid) && Instant::now() < deadline {
            sleep(Duration::from_millis(20));
        }
    };
    crash(&sup);
    let second = sup.launch_info(Duration::from_secs(60)).expect("restarted");
    assert_ne!(first.token, second.token);
    assert_eq!(sup.restarts(), 1);
    crash(&sup);
    sup.launch_info(Duration::from_secs(60))
        .expect("restarted again");
    // The third crash inside the window gives up: the student sees the "can't start" state, not a restart loop.
    crash(&sup);
    let deadline = Instant::now() + Duration::from_secs(10);
    while sup.state() != State::GaveUp && Instant::now() < deadline {
        sleep(Duration::from_millis(20));
    }
    assert_eq!(sup.state(), State::GaveUp);
    assert!(sup.launch_info(Duration::from_millis(10)).is_none());
    sup.shutdown();

    // The runtime row (MDL-19, the router configuration's policy): each crash restarts it and the core goes back to
    // loading, then ready; the fourth crash in the window with no smaller model gives up, and the core, seeing it
    // gone, reports degraded (content-only) while lessons keep working.
    let (core, runtime, data) = core_with_runtime("restart-runtime", 1);
    if !plans_runtime(&core, &runtime, &data) {
        core.shutdown();
        runtime.shutdown(Duration::from_secs(1));
        return;
    }
    assert!(wait_readiness(&core, "ready", 60), "{}", core.readiness());
    for crash in 1..=4 {
        let pid = runtime.pid().expect("the runtime runs");
        kill_now(pid);
        if crash < 4 {
            assert!(runtime.wait_for(Duration::from_secs(10), |s| matches!(
                s,
                RuntimeState::Restarting { .. }
            )));
            assert!(runtime.wait_for(Duration::from_secs(30), |s| matches!(
                s,
                RuntimeState::Running { .. }
            )));
            assert!(wait_readiness(&core, "ready", 30), "{}", core.readiness());
        }
    }
    assert!(runtime.wait_for(Duration::from_secs(10), |s| matches!(
        s,
        RuntimeState::GaveUp { .. }
    )));
    assert!(
        wait_readiness(&core, "degraded", 15),
        "{}",
        core.readiness()
    );
    assert!(core.launch_info(Duration::from_secs(1)).is_some());
    core.shutdown();
    runtime.shutdown(Duration::from_secs(1));
}

#[test]
fn arc24_orphan_check_uses_start_time() {
    let data = scratch("orphans");
    let mut unrelated = Command::new(python())
        .args(["-c", "import time; time.sleep(30)"])
        .spawn()
        .unwrap();
    let pid = unrelated.id();
    let real = orphans::identify(pid).expect("the process runs");
    // A stale record whose PID was reused by an unrelated process (other start time) is not killed.
    let stale = Record {
        start_time: real.start_time.saturating_sub(3600),
        ..real.clone()
    };
    orphans::save(&data.join("pids.json"), &[stale]).unwrap();
    assert!(orphans::recover(&data.join("pids.json")).is_empty());
    assert!(alive(pid));
    // A record that matches PID, executable and start time is the orphan, and it is ended.
    orphans::save(&data.join("pids.json"), &[real]).unwrap();
    assert_eq!(orphans::recover(&data.join("pids.json")), vec![pid]);
    let _ = unrelated.wait();
}

#[test]
fn test_arc04_shell_passes_no_secret_in_argv_or_env() {
    let data = scratch("secrets");
    let sup = Supervisor::start(core(&data), Policy::default(), None);
    let info = sup.launch_info(Duration::from_secs(60)).expect("ready");
    let system = system();
    for (pid, _) in tree(sup.pid().unwrap()) {
        if let Some(process) = system.process(Pid::from_u32(pid)) {
            let argv = process
                .cmd()
                .iter()
                .map(|s| s.to_string_lossy())
                .collect::<Vec<_>>()
                .join(" ");
            let env = process
                .environ()
                .iter()
                .map(|s| s.to_string_lossy())
                .collect::<Vec<_>>()
                .join(" ");
            assert!(
                !argv.contains(&info.token) && !env.contains(&info.token),
                "pid {pid}"
            );
        }
    }
    sup.shutdown();
}

/// A stand-in core whose exit steps after `control.shutdown` take longer than the turn grace it was given (turns that
/// used their whole grace, then the learner snapshot before an update installs at quit), then hands over the update.
const SLOW_EXIT_CORE: &str = r#"
import json, sys, time
for line in sys.stdin:
    message = json.loads(line)
    if message["type"] == "control.secret":
        print(json.dumps({"type": "control.ready", "protocol": {"major": 1, "minor": 4}, "api_port": 9,
                          "epoch": "0123456789abcdef"}), flush=True)
    elif message["type"] == "control.shutdown":
        time.sleep(message["grace_ms"] / 1000 + 1.5)
        print(json.dumps({"type": "control.update_install", "installer": "jana-setup.exe", "sha256": "0" * 64,
                          "size_bytes": 1, "version": "1.0.1", "action": "update"}), flush=True)
        print(json.dumps({"type": "control.bye"}), flush=True)
        break
"#;

/// ARC-23 with PLT-14: the shell lets the core finish its own exit steps (here past the turn grace) instead of
/// killing it one step deadline after asking, so an update accepted for quit is handed over, not skipped; the quit
/// still ends inside the total deadline.
#[test]
fn test_arc23_core_finishes_its_exit_steps() {
    let data = scratch("slow-exit");
    let mut command = core(&data);
    command.args = vec!["-c".into(), SLOW_EXIT_CORE.into()];
    let policy = Policy::default();
    let sup = Supervisor::start(command, policy.clone(), None);
    sup.launch_info(Duration::from_secs(30)).expect("ready");
    let took = sup.shutdown();
    assert!(took > policy.step_deadline, "{took:?}");
    assert!(took <= policy.total_deadline, "{took:?}");
    assert_eq!(sup.state(), State::Stopped);
    let plan = sup
        .take_update_install()
        .expect("the update is handed over");
    assert_eq!(plan.version, "1.0.1");
}

/// The commands the webview may invoke: exactly those the UI calls (`apps/desktop/src/launch.ts`).
const UI_COMMANDS: [&str; 5] = [
    "launch_info",
    "pick_install_source",
    "pick_profile_archive",
    "update_recovery",
    "rollback_update",
];

/// The identifiers in `text` after each `marker`, up to `end`.
fn names_between(text: &str, marker: &str, end: &str) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for part in text.split(marker).skip(1) {
        let body = part.split(end).next().unwrap_or_default();
        out.extend(
            body.split(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
                .filter(|w| !w.is_empty())
                .map(String::from),
        );
    }
    out
}

// The ACL fixture: stand-ins with the app's command names (the real handlers live in the binary) behind the app's
// own build manifest and capability file, so the test drives the ACL the app ships with.
#[tauri::command]
fn launch_info() -> &'static str {
    "ok"
}
#[tauri::command]
fn pick_install_source() -> &'static str {
    "ok"
}
#[tauri::command]
fn pick_profile_archive() -> &'static str {
    "ok"
}
#[tauri::command]
fn update_recovery() -> &'static str {
    "ok"
}
#[tauri::command]
fn rollback_update() -> &'static str {
    "ok"
}
#[tauri::command]
fn not_declared() -> &'static str {
    "ok"
}

fn invoke(webview: &tauri::WebviewWindow<tauri::test::MockRuntime>, cmd: &str) -> bool {
    tauri::test::get_ipc_response(
        webview,
        tauri::webview::InvokeRequest {
            cmd: cmd.into(),
            callback: tauri::ipc::CallbackFn(0),
            error: tauri::ipc::CallbackFn(1),
            url: if cfg!(windows) {
                "http://tauri.localhost"
            } else {
                "tauri://localhost"
            }
            .parse()
            .unwrap(),
            body: tauri::ipc::InvokeBody::default(),
            headers: Default::default(),
            invoke_key: tauri::test::INVOKE_KEY.to_string(),
        },
    )
    .is_ok()
}

/// A synchronous Tauri command runs on the main thread: one that waits (for a starting core, a dialog, a process)
/// freezes the window. Every command the app registers is async and does its waiting off that thread.
#[test]
fn commands_never_block_the_window() {
    let main =
        std::fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/main.rs"))
            .unwrap();
    let commands: Vec<&str> = main
        .split("#[tauri::command]")
        .skip(1)
        .map(|after| after.trim_start().lines().next().unwrap_or_default())
        .collect();
    assert_eq!(commands.len(), UI_COMMANDS.len());
    for signature in commands {
        assert!(signature.starts_with("async fn "), "{signature}");
    }
}

#[test]
fn sec11_capabilities_minimal() {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let read = |path: &str| std::fs::read_to_string(dir.join(path)).unwrap();
    let expected: BTreeSet<String> = UI_COMMANDS.map(String::from).into();
    // The UI, the handler list, the build manifest and the capability file name the same commands.
    assert_eq!(
        names_between(&read("../src/launch.ts"), "tauri.invoke(\"", "\""),
        expected,
        "the commands the UI invokes"
    );
    assert_eq!(
        names_between(&read("src/main.rs"), "generate_handler![", "]"),
        expected,
        "the commands the app registers"
    );
    assert_eq!(
        names_between(&read("build.rs"), ".commands(&[", "]"),
        expected,
        "the commands the app manifest declares"
    );
    let capability: serde_json::Value =
        serde_json::from_str(&read("capabilities/default.json")).unwrap();
    let granted: BTreeSet<String> = capability["permissions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p.as_str().unwrap().to_string())
        .collect();
    // Only the app's own commands: no core or plugin permission, so no shell, file-system or HTTP plugin and no
    // dialog API reaches the webview (the file picker runs in the shell behind `pick_install_source`).
    let allow: BTreeSet<String> = UI_COMMANDS
        .iter()
        .map(|c| format!("allow-{}", c.replace('_', "-")))
        .collect();
    assert_eq!(granted, allow);
    assert_eq!(capability["windows"], serde_json::json!(["main"]));
    assert!(capability.get("remote").is_none(), "no remote origin");
    assert_eq!(
        std::fs::read_dir(dir.join("capabilities")).unwrap().count(),
        1
    );

    // The shipped ACL: every UI command is allowed from the app's origin; anything else is refused.
    let app = tauri::test::mock_builder()
        .invoke_handler(tauri::generate_handler![
            launch_info,
            pick_install_source,
            pick_profile_archive,
            update_recovery,
            rollback_update,
            not_declared
        ])
        .build(tauri::generate_context!())
        .unwrap();
    let webview = tauri::WebviewWindowBuilder::new(&app, "main", Default::default())
        .build()
        .unwrap();
    for command in UI_COMMANDS {
        assert!(invoke(&webview, command), "{command} is refused");
    }
    for command in [
        "not_declared",
        "plugin:dialog|open",
        "plugin:window|close",
        "plugin:event|listen",
    ] {
        assert!(!invoke(&webview, command), "{command} is allowed");
    }

    // The CSP: bundled assets only; the core over loopback HTTP on any port and, from S3, the voice socket over
    // loopback WebSocket (VOC-26); local previews only.
    let conf: serde_json::Value = serde_json::from_str(&read("tauri.conf.json")).unwrap();
    let csp = &conf["app"]["security"]["csp"];
    assert_eq!(csp["default-src"], "'self'");
    assert_eq!(csp["script-src"], "'self'");
    assert_eq!(csp["object-src"], "'none'");
    assert_eq!(
        csp["connect-src"],
        "'self' http://127.0.0.1:* ws://127.0.0.1:*"
    );
    assert_eq!(csp["img-src"], "'self' data: blob:");
    assert_eq!(csp["media-src"], "'self' blob:");
    assert!(!conf.to_string().contains("unsafe-eval"));
    assert_eq!(conf["app"]["withGlobalTauri"], false);
    let cargo = read("Cargo.toml");
    for plugin in ["tauri-plugin-shell", "tauri-plugin-fs", "tauri-plugin-http"] {
        assert!(!cargo.contains(plugin), "{plugin}");
    }
}
