//! The shell's runtime supervisor (ARC-02, ARC-23, ARC-24, MDL-19) against a stand-in for llama-server: the
//! repository's fake runtime process, started with the plan's arguments, which answers on the port and with the key
//! the shell gives it. Killing it is a crash. The core is a recording stand-in for the control channel; the core's own
//! side (retry from Prepare, content-only reporting) is tested in the agent core. No real llama-server is started.

// The variant tests and their stand-ins are Unix-only (shell scripts); on Windows their helpers go unused.
#![cfg_attr(windows, allow(dead_code, unused_imports))]

use jana_shell::control::{RuntimeEndpoint, ToCore};
use jana_shell::runtime::{
    Build, Builds, CoreLink, RuntimeCommand, RuntimePolicy, RuntimeState, RuntimeSupervisor,
};
use jana_shell::variants::{self, Arch, Cpu, Os, Variant};
use serde_json::json;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread::sleep;
use std::time::{Duration, Instant};
use sysinfo::{Pid, ProcessRefreshKind, ProcessesToUpdate, System, UpdateKind};

const EPOCH: &str = "0123456789abcdef";

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

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("jana-runtime-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("runtime/models/big-model")).unwrap();
    std::fs::create_dir_all(dir.join("runtime/models/small-model")).unwrap();
    dir
}

/// The control channel as the runtime supervisor sees it: a ready core that records what it is sent.
#[derive(Default)]
struct FakeCore {
    epoch: Mutex<Option<String>>,
    sent: Mutex<Vec<ToCore>>,
}

impl FakeCore {
    fn ready(epoch: &str) -> Arc<FakeCore> {
        let core = FakeCore::default();
        *core.epoch.lock().unwrap() = Some(epoch.into());
        Arc::new(core)
    }

    /// The endpoints sent so far: (url, key, model).
    fn endpoints(&self) -> Vec<(String, String, String)> {
        self.sent
            .lock()
            .unwrap()
            .iter()
            .filter_map(|m| match m {
                ToCore::RuntimeEndpoint(RuntimeEndpoint { url, key, model }) => {
                    Some((url.clone(), key.reveal().to_string(), model.clone()))
                }
                _ => None,
            })
            .collect()
    }

    fn wait_endpoints(&self, count: usize) -> Vec<(String, String, String)> {
        let deadline = Instant::now() + Duration::from_secs(30);
        while self.endpoints().len() < count && Instant::now() < deadline {
            sleep(Duration::from_millis(20));
        }
        self.endpoints()
    }
}

impl CoreLink for FakeCore {
    fn ready_epoch(&self) -> Option<String> {
        self.epoch.lock().unwrap().clone()
    }

    fn send(&self, message: &ToCore) -> bool {
        self.sent.lock().unwrap().push(message.clone());
        true
    }
}

fn fake_runtime() -> RuntimeCommand {
    RuntimeCommand {
        program: python(),
        prefix_args: vec!["-m".into(), "jana_tools.fakes.llama_server".into()],
    }
}

/// A plan as the core writes it (synthetic models; the fake runtime ignores the flags it does not serve).
fn write_plan(dir: &Path, models: &[&str], backoff: &[f64]) -> PathBuf {
    let models_dir = dir.join("runtime/models");
    let attempts: Vec<_> = models
        .iter()
        .map(|m| {
            json!({"model": m, "context": 6144, "args": ["--host", "127.0.0.1", "--models-dir", models_dir,
                   "--models-max", "1", "--ctx-size", "6144", "--parallel", "1", "--no-webui",
                   "--no-context-shift", "--jinja"]})
        })
        .collect();
    let plan = json!({"plan_version": 1, "epoch": EPOCH, "model": models[0], "reason": null,
                      "hardware_class": "low", "models_dir": models_dir, "attempts": attempts,
                      "restart": {"backoff_s": backoff, "max_restarts": 3, "window_s": 300.0}, "left_out": []});
    let path = dir.join("runtime/launch.json");
    std::fs::write(&path, serde_json::to_vec(&plan).unwrap()).unwrap();
    path
}

fn policy() -> RuntimePolicy {
    RuntimePolicy {
        start_deadline: Duration::from_secs(20),
        step_deadline: Duration::from_secs(3),
    }
}

fn system() -> System {
    let mut system = System::new();
    system.refresh_processes_specifics(
        ProcessesToUpdate::All,
        true,
        ProcessRefreshKind::nothing()
            .with_cmd(UpdateKind::Always)
            .with_environ(UpdateKind::Always),
    );
    system
}

fn alive(pid: u32) -> bool {
    system().process(Pid::from_u32(pid)).is_some_and(|p| {
        !matches!(
            p.status(),
            sysinfo::ProcessStatus::Zombie | sysinfo::ProcessStatus::Dead
        )
    })
}

/// Kill the running runtime as a crash would, and wait until the supervisor has noticed.
fn crash(sup: &RuntimeSupervisor) -> u32 {
    let pid = sup.pid().expect("a runtime runs");
    kill_now(pid);
    let deadline = Instant::now() + Duration::from_secs(10);
    while sup.pid() == Some(pid) && Instant::now() < deadline {
        sleep(Duration::from_millis(10));
    }
    pid
}

fn running(sup: &RuntimeSupervisor) -> bool {
    sup.wait_for(Duration::from_secs(30), |s| {
        matches!(s, RuntimeState::Running { .. })
    })
}

#[test]
fn mdl19_crash_restart() {
    let dir = scratch("restart");
    let plan = write_plan(&dir, &["big-model"], &[0.3, 0.6, 1.2]);
    let core = FakeCore::ready(EPOCH);
    let pids = dir.join("runtime-pids.json");
    let sup = RuntimeSupervisor::start(
        core.clone(),
        plan,
        fake_runtime(),
        policy(),
        Some(pids.clone()),
    );
    assert!(running(&sup), "{:?}", sup.state());
    let first = core.wait_endpoints(1);
    let (url, key, model) = first[0].clone();
    assert!(url.starts_with("http://127.0.0.1:") && model == "big-model" && key.len() >= 32);
    // The key reached the runtime through a 0600 file that is gone once it answered; never argv or environment.
    let key_file = dir.join("runtime/key");
    assert!(!key_file.exists());
    let pid = sup.pid().unwrap();
    let system = system();
    let process = system.process(Pid::from_u32(pid)).unwrap();
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
    assert!(argv.contains("--no-context-shift") && argv.contains("--ctx-size 6144"));
    assert!(!argv.contains(&key) && !env.contains(&key));
    assert!(orphans_record_names(&pids, pid));
    // Killing the runtime restarts it after the first backoff, with a new key and a new endpoint for the core.
    let crashed_at = Instant::now();
    let old = crash(&sup);
    let second = core.wait_endpoints(2);
    assert_eq!(second.len(), 2, "{:?}", sup.state());
    assert!(crashed_at.elapsed() >= Duration::from_millis(300));
    assert_ne!(second[1].1, key);
    assert_eq!(second[1].2, "big-model");
    assert!(!alive(old));
    assert_eq!(sup.launches(), 2);
    // OBS-16: the crash left one record in the core's crash inbox: the runtime's, with its exit and stderr tail.
    let records = crash_records(&dir);
    assert_eq!(records.len(), 1, "{records:?}");
    assert_eq!(records[0]["process"], "runtime");
    assert_eq!(records[0]["kind"], "runtime_exit");
    assert!(records[0]["detail"].get("exit_code").is_some());
    assert!(records[0]["log_tail"].is_array());
    // Quit stops it within the step deadline and leaves no runtime, key file or PID record behind (ARC-23); a stop
    // is not a crash.
    let pid = sup.pid().unwrap();
    let took = sup.shutdown(Duration::from_secs(3));
    assert!(took < Duration::from_secs(4), "{took:?}");
    sleep(Duration::from_millis(200));
    assert!(!alive(pid));
    assert_eq!(sup.state(), RuntimeState::Stopped);
    assert!(!key_file.exists() && !pids.exists());
    assert_eq!(crash_records(&dir).len(), 1);
}

fn crash_records(data: &Path) -> Vec<serde_json::Value> {
    std::fs::read_dir(data.join("crashes/inbox"))
        .map(|entries| {
            entries
                .flatten()
                .filter(|e| e.path().extension().is_some_and(|x| x == "json"))
                .map(|e| serde_json::from_slice(&std::fs::read(e.path()).unwrap()).unwrap())
                .collect()
        })
        .unwrap_or_default()
}

fn orphans_record_names(path: &Path, pid: u32) -> bool {
    jana_shell::orphans::load(path).iter().any(|r| r.pid == pid)
}

#[test]
fn mdl19_restart_limit() {
    // With a smaller model installed: the fourth crash inside the window switches to it, once.
    let dir = scratch("limit");
    let plan = write_plan(&dir, &["big-model", "small-model"], &[0.05, 0.1, 0.2]);
    let core = FakeCore::ready(EPOCH);
    let sup = RuntimeSupervisor::start(core.clone(), plan, fake_runtime(), policy(), None);
    for crashes in 1..=3 {
        assert!(running(&sup));
        core.wait_endpoints(crashes);
        crash(&sup);
        assert_eq!(core.wait_endpoints(crashes + 1).len(), crashes + 1);
    }
    assert!(running(&sup));
    crash(&sup); // the fourth crash in the window
    let endpoints = core.wait_endpoints(5);
    assert_eq!(
        endpoints.iter().map(|e| e.2.as_str()).collect::<Vec<_>>(),
        [
            "big-model",
            "big-model",
            "big-model",
            "big-model",
            "small-model"
        ]
    );
    // The smaller model gets the same policy; its fourth crash gives up: content-only, nothing left running.
    for crashes in 5..=7 {
        assert!(running(&sup));
        crash(&sup);
        assert_eq!(core.wait_endpoints(crashes + 1).len(), crashes + 1);
    }
    assert!(running(&sup));
    let last = crash(&sup);
    assert!(sup.wait_for(Duration::from_secs(10), |s| matches!(
        s,
        RuntimeState::GaveUp { .. }
    )));
    sleep(Duration::from_millis(300));
    assert_eq!(core.endpoints().len(), 8);
    assert_eq!(sup.pid(), None);
    assert!(!alive(last));
    sup.shutdown(Duration::from_secs(1));

    // With no smaller model installed, the fourth crash gives up at once.
    let dir = scratch("limit-one");
    let plan = write_plan(&dir, &["big-model"], &[0.05, 0.1, 0.2]);
    let core = FakeCore::ready(EPOCH);
    let sup = RuntimeSupervisor::start(core.clone(), plan, fake_runtime(), policy(), None);
    for crashes in 1..=4 {
        assert!(running(&sup));
        core.wait_endpoints(crashes);
        crash(&sup);
    }
    assert!(sup.wait_for(Duration::from_secs(10), |s| *s
        == RuntimeState::GaveUp {
            reason: "restart_limit".into()
        }));
    assert_eq!(core.endpoints().len(), 4);
    sup.shutdown(Duration::from_secs(1));
}

#[test]
fn runtime_orphans_and_stale_plans() {
    // A plan written by another core process (an old epoch) starts nothing: the core rewrites it before ready.
    let dir = scratch("stale");
    let plan = write_plan(&dir, &["big-model"], &[0.05]);
    let core = FakeCore::ready("fedcba9876543210");
    let sup = RuntimeSupervisor::start(core.clone(), plan.clone(), fake_runtime(), policy(), None);
    assert!(sup.wait_for(Duration::from_secs(5), |s| *s
        == RuntimeState::NoModel {
            reason: "stale_plan".into()
        }));
    assert!(core.endpoints().is_empty() && sup.pid().is_none());
    sup.shutdown(Duration::from_secs(1));
    // A runtime left by a shell that died is ended at the next start, by its recorded identity (ARC-24).
    std::fs::write(dir.join("runtime/key"), "k".repeat(64)).unwrap();
    let mut orphan = Command::new(python())
        .args([
            "-m",
            "jana_tools.fakes.llama_server",
            "--port",
            "0",
            "--api-key-file",
        ])
        .arg(dir.join("runtime/key"))
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    sleep(Duration::from_millis(300));
    let pids = dir.join("runtime-pids.json");
    jana_shell::orphans::track(&pids, orphan.id());
    let core = FakeCore::ready("fedcba9876543210");
    let sup = RuntimeSupervisor::start(core, plan, fake_runtime(), policy(), Some(pids.clone()));
    let _ = orphan.wait();
    assert!(!pids.exists());
    sup.shutdown(Duration::from_secs(1));
}

// --- PLT-04: runtime builds ---------------------------------------------------------------------------------------

/// A core stand-in that does what the real core does with an endpoint: report `model_loading`, run one touch
/// generation against the runtime with the launch's key, then report `ready` or `degraded` (ARC-22, MDL-20).
struct TouchingCore {
    sent: Mutex<Vec<ToCore>>,
    readiness: Arc<Mutex<String>>,
}

impl TouchingCore {
    fn new() -> Arc<TouchingCore> {
        Arc::new(TouchingCore {
            sent: Mutex::new(vec![]),
            readiness: Arc::new(Mutex::new("core_ready".into())),
        })
    }

    fn models(&self) -> Vec<String> {
        self.sent
            .lock()
            .unwrap()
            .iter()
            .filter_map(|m| match m {
                ToCore::RuntimeEndpoint(RuntimeEndpoint { model, .. }) => Some(model.clone()),
                _ => None,
            })
            .collect()
    }
}

fn touch(url: &str, key: &str) -> bool {
    use std::io::{Read, Write};
    let address = url.trim_start_matches("http://");
    let Ok(mut stream) = std::net::TcpStream::connect(address) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(10)));
    let body = r#"{"model":"m","messages":[{"role":"user","content":"Say OK."}],"max_tokens":8}"#;
    let request = format!(
        "POST /v1/chat/completions HTTP/1.0\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {key}\r\n\
         Content-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
        body.len()
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut reply = String::new();
    let _ = stream.read_to_string(&mut reply);
    reply.starts_with("HTTP/1.1 200")
}

impl CoreLink for TouchingCore {
    fn ready_epoch(&self) -> Option<String> {
        Some(EPOCH.into())
    }

    fn send(&self, message: &ToCore) -> bool {
        if let ToCore::RuntimeEndpoint(RuntimeEndpoint { url, key, .. }) = message {
            *self.readiness.lock().unwrap() = "model_loading".into();
            let (url, key, readiness) = (
                url.clone(),
                key.reveal().to_string(),
                self.readiness.clone(),
            );
            std::thread::spawn(move || {
                let ok = touch(&url, &key);
                *readiness.lock().unwrap() = if ok { "ready" } else { "degraded" }.into();
            });
        }
        self.sent.lock().unwrap().push(message.clone());
        true
    }

    fn readiness(&self) -> Option<String> {
        Some(self.readiness.lock().unwrap().clone())
    }
}

/// A bundle's `resources/runtime/<variant>/llama-server`, as a script around the fake runtime with test-only flags
/// (or any other shell body), so the real selection and supervision code runs against it.
fn bundle_build(resources: &Path, variant: &str, body: &str) {
    let dir = resources.join("runtime").join(variant);
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("llama-server");
    std::fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
    }
}

fn fake_body(flags: &str) -> String {
    format!(
        "exec '{}' -m jana_tools.fakes.llama_server {flags} \"$@\" 2>/dev/null",
        repo().join(".venv/bin/python").display()
    )
}

fn variant_record(dir: &Path) -> serde_json::Value {
    serde_json::from_slice(&std::fs::read(dir.join("runtime/variant.json")).unwrap()).unwrap()
}

fn x86(avx2: bool) -> Cpu {
    Cpu {
        os: Os::Linux,
        arch: Arch::X86_64,
        sse42: true,
        avx2,
        fma: avx2,
    }
}

fn wait_ready(core: &TouchingCore) -> bool {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if core.readiness().as_deref() == Some("ready") {
            return true;
        }
        sleep(Duration::from_millis(20));
    }
    false
}

#[test]
#[cfg(unix)] // the stand-in builds are shell scripts
fn plt04_vulkan_failure_falls_back() {
    // A Vulkan device that qualifies, whose driver crashes on the first generation; the CPU builds work.
    let dir = scratch("vulkan");
    let resources = dir.join("resources");
    let device =
        "--fake-device 'Vulkan0: NVIDIA GeForce RTX 3050 Laptop GPU (4096 MiB, 3900 MiB free)'";
    bundle_build(
        &resources,
        "vulkan",
        &fake_body(&format!("{device} --fake-crash-on-generation")),
    );
    bundle_build(&resources, "cpu-avx2", &fake_body(""));
    bundle_build(&resources, "cpu-baseline", &fake_body(""));
    let builds = variants::select(&resources, x86(true), &[]);
    let order: Vec<_> = builds.ladder.iter().map(|b| b.variant.unwrap()).collect();
    assert_eq!(
        order,
        [Variant::Vulkan, Variant::CpuAvx2, Variant::CpuBaseline]
    );
    let plan = write_plan(&dir, &["big-model"], &[0.05, 0.1, 0.2]);
    let core = TouchingCore::new();
    let sup = RuntimeSupervisor::start_builds(
        core.clone(),
        plan,
        Box::new(move || builds),
        policy(),
        None,
    );
    // The Vulkan build crashes during the touch generation; cpu-avx2 starts the same model and passes it.
    assert!(wait_ready(&core), "{:?}", sup.state());
    assert_eq!(core.models(), ["big-model", "big-model"]);
    assert_eq!(sup.launches(), 2);
    assert!(matches!(sup.state(), RuntimeState::Running { .. }));
    // The build in use and why the first was set aside, for the core's health panel (OBS-15).
    let record = variant_record(&dir);
    assert_eq!(record["epoch"], EPOCH);
    assert_eq!(record["variant"], "cpu-avx2");
    assert_eq!(record["fallbacks"][0]["variant"], "vulkan");
    let why = record["fallbacks"][0]["reason"].as_str().unwrap();
    assert!(
        why.contains("segmentation fault") && why.contains("first generation"),
        "{why}"
    );
    // A fallback is not a crash of the model: a later crash of the proven build follows the restart policy (MDL-19).
    crash(&sup);
    assert!(running(&sup) && wait_ready(&core));
    assert_eq!(variant_record(&dir)["variant"], "cpu-avx2");
    assert_eq!(sup.launches(), 3);
    sup.shutdown(Duration::from_secs(1));

    // A Vulkan driver whose device probe itself crashes is left out before anything starts, with why.
    let resources = dir.join("resources-probe");
    bundle_build(&resources, "vulkan", "kill -SEGV $$");
    bundle_build(&resources, "cpu-avx2", &fake_body(""));
    let builds = variants::select(&resources, x86(true), &[]);
    assert_eq!(builds.ladder[0].variant, Some(Variant::CpuAvx2));
    assert_eq!(builds.skipped[0].0, Variant::Vulkan);
    assert!(
        builds.skipped[0].1.contains("segmentation fault"),
        "{:?}",
        builds.skipped
    );
}

#[test]
#[cfg(unix)] // the stand-in builds are shell scripts
fn plt04_no_avx2_selects_baseline() {
    // The AVX2 build would die of an illegal instruction on this CPU; it must never be started.
    let dir = scratch("baseline");
    let resources = dir.join("resources");
    bundle_build(&resources, "cpu-avx2", "kill -ILL $$");
    bundle_build(&resources, "cpu-baseline", &fake_body(""));
    let builds = variants::select(&resources, x86(false), &[]);
    let order: Vec<_> = builds.ladder.iter().map(|b| b.variant.unwrap()).collect();
    assert_eq!(order, [Variant::CpuBaseline]);
    assert_eq!(
        builds.skipped,
        [(Variant::CpuAvx2, "the CPU has no AVX2 and FMA".to_string())]
    );
    let plan = write_plan(&dir, &["big-model"], &[0.05]);
    let core = TouchingCore::new();
    let sup = RuntimeSupervisor::start_builds(
        core.clone(),
        plan,
        Box::new(move || builds),
        policy(),
        None,
    );
    assert!(wait_ready(&core), "{:?}", sup.state());
    assert_eq!(sup.launches(), 1);
    let record = variant_record(&dir);
    assert_eq!(record["variant"], "cpu-baseline");
    assert_eq!(record["fallbacks"], json!([]));
    assert_eq!(record["rejected"][0]["variant"], "cpu-avx2");
    sup.shutdown(Duration::from_secs(1));

    // Had the AVX2 build been tried, its illegal instruction would be named and the baseline build started instead.
    let dir = scratch("baseline-forced");
    let plan = write_plan(&dir, &["big-model"], &[0.05]);
    let forced = Builds {
        ladder: [Variant::CpuAvx2, Variant::CpuBaseline]
            .into_iter()
            .map(|variant| Build {
                variant: Some(variant),
                command: RuntimeCommand {
                    program: variants::program(&resources, variant),
                    prefix_args: vec![],
                },
            })
            .collect(),
        skipped: vec![],
    };
    let core = TouchingCore::new();
    let sup = RuntimeSupervisor::start_builds(
        core.clone(),
        plan,
        Box::new(move || forced),
        policy(),
        None,
    );
    assert!(wait_ready(&core), "{:?}", sup.state());
    let record = variant_record(&dir);
    assert_eq!(record["variant"], "cpu-baseline");
    assert_eq!(
        record["fallbacks"][0]["reason"],
        "illegal instruction before it answered"
    );
    sup.shutdown(Duration::from_secs(1));

    // No build this machine may run: no runtime, and the core reports content-only.
    let dir = scratch("baseline-none");
    let plan = write_plan(&dir, &["big-model"], &[0.05]);
    let sup = RuntimeSupervisor::start_builds(
        TouchingCore::new(),
        plan,
        Box::new(Builds::default),
        policy(),
        None,
    );
    assert!(sup.wait_for(Duration::from_secs(10), |s| *s
        == RuntimeState::GaveUp {
            reason: "no_runtime_variant".into()
        }));
    sup.shutdown(Duration::from_secs(1));
}
