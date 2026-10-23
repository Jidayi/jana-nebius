//! The shell's crash capture (OBS-16): a panic hook that writes a crash record the core takes in, and runtime exits
//! with their exit code and stderr tail.
//!
//! On a panic the hook writes `crashes/inbox/<id>.json`: process `shell`, the app version, the stack as module and
//! offset per frame, the core epoch as correlation id, and no panic message (it may quote a path or text). The core's
//! crash store reads the inbox at its next start, re-checks each record and lists it in the health panel; records
//! hold no memory. Fatal signals and the out-of-process minidump need a minidump writer (owner item: the
//! `minidump-writer` and `crash-handler` dependencies and an AEAD crate, so the dump is sealed under the device key
//! before it touches the disk); until then a fatal signal leaves the supervisor's restart record only.

use serde_json::{Value, json};
use std::backtrace::Backtrace;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_FRAMES: usize = 200;
const LINE_MAX: usize = 300;

static EPOCH: OnceLock<Mutex<Option<String>>> = OnceLock::new();

/// The core epoch the shell is talking to, recorded as the crash's correlation id.
pub fn set_epoch(epoch: &str) {
    let slot = EPOCH.get_or_init(|| Mutex::new(None));
    if let Ok(mut held) = slot.lock() {
        *held = Some(epoch.to_string());
    }
}

fn epoch() -> Option<String> {
    EPOCH.get()?.lock().ok()?.clone()
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default()
}

/// Frames as module and offset: the symbol's crate path without arguments, or the raw address.
pub fn frames(trace: &str) -> Vec<Value> {
    let mut out = vec![];
    for line in trace.lines() {
        let line = line.trim();
        let Some((index, rest)) = line.split_once(": ") else {
            continue;
        };
        if index.parse::<u32>().is_err() {
            continue;
        }
        let symbol = rest.split("::h").next().unwrap_or(rest);
        let module = symbol.rsplit_once("::").map_or(symbol, |(m, _)| m);
        out.push(
            json!({"module": module.chars().take(LINE_MAX).collect::<String>(), "offset": symbol
            .rsplit("::").next().unwrap_or_default().chars().take(80).collect::<String>()}),
        );
        if out.len() >= MAX_FRAMES {
            break;
        }
    }
    out
}

/// One crash record as the core's inbox reads it.
pub fn record(
    kind: &str,
    version: &str,
    stack: Vec<Value>,
    log_tail: &[String],
    extra: Value,
) -> Value {
    let mut correlation = serde_json::Map::new();
    if let Some(epoch) = epoch() {
        correlation.insert("epoch".into(), Value::String(epoch));
    }
    json!({
        "process": if kind == "runtime_exit" { "runtime" } else { "shell" },
        "kind": kind,
        "version": version,
        "error_type": extra.get("error_type").cloned().unwrap_or(Value::Null),
        "stack": stack,
        "correlation": correlation,
        "log_tail": log_tail.iter().map(|l| l.chars().take(LINE_MAX).collect::<String>()).collect::<Vec<_>>(),
        "detail": extra.get("detail").cloned().unwrap_or_else(|| json!({})),
    })
}

/// Write a record into `<crashes>/inbox/` (atomically: a temporary name, then a rename).
pub fn write_record(crashes: &Path, record: &Value) -> std::io::Result<PathBuf> {
    let inbox = crashes.join("inbox");
    fs::create_dir_all(&inbox)?;
    let name = format!("{}-{}.json", now_ms(), std::process::id());
    let temp = inbox.join(format!("{name}.tmp"));
    let mut file = fs::File::create(&temp)?;
    file.write_all(serde_json::to_string(record).unwrap_or_default().as_bytes())?;
    file.sync_all()?;
    let path = inbox.join(name);
    fs::rename(temp, &path)?;
    Ok(path)
}

/// A runtime exit (llama-server ended unexpectedly): exit code and the last `tail_lines` stderr lines.
pub fn runtime_exit(
    crashes: &Path,
    version: &str,
    exit_code: Option<i32>,
    stderr: &[String],
    tail_lines: usize,
) -> std::io::Result<PathBuf> {
    let tail = &stderr[stderr.len().saturating_sub(tail_lines)..];
    let rec = record(
        "runtime_exit",
        version,
        vec![],
        tail,
        json!({"detail": {"exit_code": exit_code}}),
    );
    write_record(crashes, &rec)
}

/// Install the panic hook for the life of the shell; the previous hook still runs (it prints in development).
pub fn install_panic_hook(crashes: PathBuf, version: &'static str) {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let trace = Backtrace::force_capture().to_string();
        let error_type = if info.payload().is::<&str>() || info.payload().is::<String>() {
            "panic"
        } else {
            "panic_payload"
        };
        let rec = record(
            "panic",
            version,
            frames(&trace),
            &[],
            json!({"error_type": error_type}),
        );
        let _ = write_record(&crashes, &rec);
        previous(info);
    }));
}

#[cfg(test)]
mod tests {
    use super::*;

    /// OBS-16 (shell half): an injected panic produces a crash record with a stack and the core epoch as correlation
    /// id, and no panic message; a runtime exit produces one with the exit code and only the stderr tail.
    #[test]
    fn obs16_crash_record_per_process() {
        let dir = std::env::temp_dir().join(format!("jana-crash-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        set_epoch("0123456789abcdef");
        install_panic_hook(dir.clone(), "1.2.3");
        let outcome = std::thread::spawn(|| {
            let secret_text = "the student's question";
            panic!("{secret_text}");
        })
        .join();
        assert!(outcome.is_err());
        let _ = std::panic::take_hook(); // later tests panic normally
        let records: Vec<Value> = fs::read_dir(dir.join("inbox"))
            .unwrap()
            .map(|e| serde_json::from_slice(&fs::read(e.unwrap().path()).unwrap()).unwrap())
            .collect();
        assert_eq!(records.len(), 1);
        let rec = &records[0];
        assert_eq!(rec["process"], "shell");
        assert_eq!(rec["kind"], "panic");
        assert_eq!(rec["version"], "1.2.3");
        assert_eq!(rec["correlation"]["epoch"], "0123456789abcdef");
        assert!(
            !rec["stack"].as_array().unwrap().is_empty(),
            "the record has a stack"
        );
        assert!(
            !rec.to_string().contains("student's question"),
            "no panic message is kept"
        );

        let stderr: Vec<String> = (0..500).map(|i| format!("line {i}")).collect();
        let path = runtime_exit(&dir, "1.2.3", Some(139), &stderr, 200).unwrap();
        let exit: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(exit["process"], "runtime");
        assert_eq!(exit["detail"]["exit_code"], 139);
        assert_eq!(exit["log_tail"].as_array().unwrap().len(), 200);
        assert_eq!(exit["log_tail"][0], "line 300");
        assert_eq!(exit["correlation"]["epoch"], "0123456789abcdef");
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn frames_keep_module_and_offset_only() {
        let trace = "   0: std::backtrace::Backtrace::create\n             at /rustc/x/library/std/src/backtrace.rs:331:13\n   1: jana_shell::crash::tests::x::h0123456789abcdef\n";
        let parsed = frames(trace);
        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[1]["module"], "jana_shell::crash::tests");
        assert_eq!(parsed[1]["offset"], "x");
    }
}
