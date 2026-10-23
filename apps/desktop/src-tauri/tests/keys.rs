//! The keychain bridge and the network hint on the control channel (SEC-17, D97; ARC-08), driven through the real
//! supervisor against a scripted core: what the shell sends at each start, and how it answers key requests. The key
//! store is the SEC-17 file fallback in a scratch folder; no test here touches the OS keychain.

use jana_shell::control::Config;
use jana_shell::keychain::KeyStore;
use jana_shell::supervisor::{CoreCommand, Policy, Supervisor};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

fn python() -> PathBuf {
    if cfg!(windows) {
        repo().join(".venv/Scripts/python.exe")
    } else {
        repo().join(".venv/bin/python")
    }
}

/// A core that records every control frame it reads (one JSON line each) in the file its first argument names, asks
/// for two puts and a delete once it has its launch token, and stops on `control.shutdown`.
const RECORDING_CORE: &str = r#"
import json, sys
log = open(sys.argv[1], "a")
for line in sys.stdin:
    log.write(line)
    log.flush()
    message = json.loads(line)
    if message["type"] == "control.secret":
        say = lambda frame: print(json.dumps(frame), flush=True)
        if not sys.argv[2:]:
            say({"type": "control.key_put", "ref": "jana.device-db", "value": "ZGJfa2V5X3ZhbHVl"})
            say({"type": "control.key_put", "ref": "jana.service-credential.id", "value": "ZGNyX2V4YW1wbGU"})
            say({"type": "control.key_delete", "ref": "jana.device-db"})
        say({"type": "control.ready", "protocol": {"major": 1, "minor": 4}, "api_port": 9,
             "epoch": "0123456789abcdef"})
    elif message["type"] == "control.shutdown":
        print(json.dumps({"type": "control.bye"}), flush=True)
        break
"#;

static ONLINE: AtomicBool = AtomicBool::new(false);

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("jana-shell-keys-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("data")).unwrap();
    dir
}

fn command(root: &Path, log: &Path, quiet: bool) -> CoreCommand {
    let data = root.join("data");
    let mut args = vec![
        "-c".into(),
        RECORDING_CORE.into(),
        log.display().to_string(),
    ];
    if quiet {
        args.push("quiet".into());
    }
    CoreCommand {
        program: python(),
        args,
        cwd: repo(),
        config: Config {
            data_dir: data.display().to_string(),
            content_root: data.display().to_string(),
            skills_root: data.display().to_string(),
            release: true,
            dev_origins: None,
            scripted: None,
            pilot_country_file: None,
        },
        keys: Arc::new(KeyStore::files(root.join("keys"), &data).unwrap()),
        net_hint: || ONLINE.load(Ordering::SeqCst),
    }
}

fn frames(log: &Path) -> Vec<Value> {
    std::fs::read_to_string(log)
        .unwrap_or_default()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn wait_for(log: &Path, done: impl Fn(&[Value]) -> bool) -> Vec<Value> {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        let seen = frames(log);
        if done(&seen) || Instant::now() > deadline {
            return seen;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn types(frames: &[Value]) -> Vec<&str> {
    frames.iter().map(|f| f["type"].as_str().unwrap()).collect()
}

/// One test, so the network hint (a process-wide switch here) is not shared between threads.
#[test]
fn key_bridge_and_network_hint_on_the_control_channel() {
    let root = scratch("bridge");
    let first = root.join("first.jsonl");
    ONLINE.store(false, Ordering::SeqCst);
    let sup = Supervisor::start(command(&root, &first, false), Policy::default(), None);
    sup.launch_info(Duration::from_secs(20)).expect("ready");
    let seen = wait_for(&first, |f| {
        f.iter()
            .filter(|m| m["type"] == "control.key_result")
            .count()
            == 3
    });
    // First start: hello, the (empty) keys before the config, the token, then the network hint.
    assert_eq!(
        types(&seen)[..5],
        [
            "control.hello",
            "control.keys",
            "control.config",
            "control.secret",
            "control.net_state"
        ]
    );
    assert_eq!(seen[1]["store"], "user_file");
    assert_eq!(seen[1]["entries"], serde_json::json!([]));
    assert_eq!(seen[4]["online"], false);
    // A result for every request, in the order asked.
    let results: Vec<_> = seen
        .iter()
        .filter(|m| m["type"] == "control.key_result")
        .map(|m| {
            (
                m["ref"].as_str().unwrap(),
                m["op"].as_str().unwrap(),
                m["ok"].as_bool().unwrap(),
                m["store"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        results,
        [
            ("jana.device-db", "put", true, "user_file"),
            ("jana.service-credential.id", "put", true, "user_file"),
            ("jana.device-db", "delete", true, "user_file"),
        ]
    );
    // A changed network hint reaches the running core.
    ONLINE.store(true, Ordering::SeqCst);
    let seen = wait_for(&first, |f| {
        f.iter()
            .any(|m| m["type"] == "control.net_state" && m["online"] == true)
    });
    assert!(
        seen.iter()
            .any(|m| m["type"] == "control.net_state" && m["online"] == true)
    );
    sup.shutdown();

    // The next start hands the core what it stored, and nothing it deleted.
    let second = root.join("second.jsonl");
    let sup = Supervisor::start(command(&root, &second, true), Policy::default(), None);
    sup.launch_info(Duration::from_secs(20)).expect("ready");
    let seen = wait_for(&second, |f| f.len() >= 5);
    assert_eq!(seen[1]["type"], "control.keys");
    assert_eq!(
        seen[1]["entries"],
        serde_json::json!([{"ref": "jana.service-credential.id", "value": "ZGNyX2V4YW1wbGU"}])
    );
    assert_eq!(seen[4]["online"], true);
    sup.shutdown();
    // The keys folder holds the one secret, and the data folder none.
    let names: Vec<_> = std::fs::read_dir(root.join("keys"))
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    assert_eq!(names, ["jana.service-credential.id"]);
    assert!(
        std::fs::read_dir(root.join("data"))
            .unwrap()
            .next()
            .is_none()
    );
    std::fs::remove_dir_all(root).unwrap();
}
