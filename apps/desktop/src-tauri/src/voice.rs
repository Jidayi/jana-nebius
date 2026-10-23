//! Lazy speech-bundle supervision (VOC-23): stdin-only secrets, verified entry point, bounded restarts and cleanup.
//! Each launch runs inside the platform's sandbox (`voice_sandbox`) with a private scratch folder as its home.

use crate::control::{Redacted, ToCore, VoiceFailed, VoiceFailedCode};
pub use crate::control::{VoiceEndpoint, VoiceStart};
use crate::launch::Token;
use crate::voice_sandbox;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, mpsc};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Ready {
    #[serde(rename = "type")]
    kind: String,
    protocol: u32,
    port: u16,
}

pub struct VoiceSupervisor {
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
    request_id: String,
}

impl VoiceSupervisor {
    /// This is called only on control.voice_start, never as part of app bring-up.
    pub fn start(
        launch: VoiceStart,
        pid_file: PathBuf,
        send: impl Fn(ToCore) + Send + 'static,
    ) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let worker_stop = Arc::clone(&stop);
        let request_id = launch.request_id.clone();
        let worker = thread::spawn(move || supervise(launch, &pid_file, worker_stop, send));
        Self {
            stop,
            worker: Some(worker),
            request_id,
        }
    }

    pub fn matches(&self, request_id: &str) -> bool {
        self.request_id == request_id
    }
}

impl Drop for VoiceSupervisor {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

// Use the shell's existing Rustls Ed25519 verifier. Trust data is embedded in this app, never loaded from a pack.
const ANCHORS: &str =
    include_str!("../../../../services/agent-core/agent_core/config/trust_anchors.json");
const REVOCATIONS: &str =
    include_str!("../../../../services/agent-core/agent_core/config/revocation_list.json");

fn base64_bytes(value: &str) -> Option<Vec<u8>> {
    let pem = format!("-----BEGIN PUBLIC KEY-----\n{value}\n-----END PUBLIC KEY-----\n");
    rustls::pki_types::pem::from_buf(&mut pem.as_bytes())
        .ok()?
        .map(|(_, bytes)| bytes)
}

fn canonical(document: &serde_json::Value) -> Option<Vec<u8>> {
    // serde_json's default map is ordered, including nested objects; Python signs UTF-8 canonical JSON.
    serde_json::to_vec(document).ok()
}

fn unsigned(document: &serde_json::Value) -> Option<Vec<u8>> {
    let mut body = document.as_object()?.clone();
    body.remove("signature");
    canonical(&serde_json::Value::Object(body))
}

fn ed25519(public: &str, signature: &str, message: &[u8]) -> Option<()> {
    let key = base64_bytes(public)?;
    let signature = base64_bytes(signature)?;
    let provider = rustls::crypto::ring::default_provider();
    let algorithms = provider
        .signature_verification_algorithms
        .mapping
        .iter()
        .find(|(scheme, _)| *scheme == rustls::SignatureScheme::ED25519)?
        .1;
    algorithms
        .first()?
        .verify_signature(&key, message, &signature)
        .ok()
}

fn allowed_root(environment: &str, root: &str) -> bool {
    if !cfg!(debug_assertions) && !matches!(environment, "pilot" | "production") {
        return false;
    }
    matches!(
        (environment, root),
        ("dev", "test") | ("staging", "staging" | "release") | ("pilot" | "production", "release")
    )
}

fn root_for<'a>(
    anchors: &'a serde_json::Value,
    key: &str,
    environment: &str,
) -> Option<&'a serde_json::Value> {
    anchors["roots"].as_array()?.iter().find(|root| {
        root["key_id"].as_str() == Some(key)
            && allowed_root(environment, root["root"].as_str().unwrap_or(""))
    })
}

fn valid_revocations(
    document: &serde_json::Value,
    anchors: &serde_json::Value,
    environment: &str,
) -> Option<u64> {
    if document["kind"] != "revocation_list" || document["signature"]["alg"] != "ed25519" {
        return None;
    }
    let root = root_for(
        anchors,
        document["signature"]["key_id"].as_str()?,
        environment,
    )?;
    ed25519(
        root["public_key"].as_str()?,
        document["signature"]["value"].as_str()?,
        &unsigned(document)?,
    )?;
    document["revoked"].as_array()?;
    document["version"].as_u64()
}

fn read_bounded(path: &Path, max: u64) -> Option<serde_json::Value> {
    if fs::symlink_metadata(path).ok()?.file_type().is_symlink() {
        return None;
    }
    let file = File::open(path).ok()?;
    let mut bytes = Vec::new();
    file.take(max + 1).read_to_end(&mut bytes).ok()?;
    if bytes.len() as u64 > max {
        return None;
    }
    serde_json::from_slice(&bytes).ok()
}

fn revocations(
    data: &Path,
    anchors: &serde_json::Value,
    environment: &str,
) -> Option<serde_json::Value> {
    // As in the core (SEC-16): the newest valid list applies, from this build's own list and the one the core adopted
    // in the data folder (`config/revocations.json`; `revocation_list.json` where builds before 2026-10-15 kept it).
    // An edited or unverifiable file counts for nothing.
    let mut held: serde_json::Value = serde_json::from_str(REVOCATIONS).ok()?;
    let mut version = valid_revocations(&held, anchors, environment)?;
    for path in [
        data.join("config").join("revocations.json"),
        data.join("revocation_list.json"),
    ] {
        if let Some(newer) = read_bounded(&path, 4 * 1024 * 1024)
            && let Some(newer_version) = valid_revocations(&newer, anchors, environment)
            && newer_version > version
        {
            held = newer;
            version = newer_version;
        }
    }
    Some(held)
}

fn revoked(document: &serde_json::Value, key: &str) -> bool {
    document["revoked"]
        .as_array()
        .is_none_or(|rows| rows.iter().any(|row| row["key_id"].as_str() == Some(key)))
}

fn utc_time(value: &str) -> Option<String> {
    // Product signing timestamps are UTC. Normalize fractional precision before comparing validity windows.
    let text = value.strip_suffix('Z')?;
    let (seconds, fraction) = text.split_once('.').unwrap_or((text, ""));
    if seconds.len() != 19
        || !seconds.bytes().enumerate().all(|(i, b)| match i {
            4 | 7 => b == b'-',
            10 => b == b'T',
            13 | 16 => b == b':',
            _ => b.is_ascii_digit(),
        })
        || fraction.len() > 9
        || !fraction.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    let year = seconds[..4].parse::<u32>().ok()?;
    let month = seconds[5..7].parse::<usize>().ok()?;
    let day = seconds[8..10].parse::<u32>().ok()?;
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    if !(1..=12).contains(&month)
        || day == 0
        || day > days[month - 1]
        || seconds[11..13].parse::<u32>().ok()? > 23
        || seconds[14..16].parse::<u32>().ok()? > 59
        || seconds[17..19].parse::<u32>().ok()? > 59
    {
        return None;
    }
    Some(format!("{seconds}.{fraction:0<9}"))
}

fn signed_manifest(launch: &VoiceStart, data: &Path) -> Option<serde_json::Value> {
    let manifest = read_bounded(
        &Path::new(&launch.pack_dir).join("manifest.json"),
        32 * 1024 * 1024,
    )?;
    if manifest["signature"]["alg"] != "ed25519" || manifest["platform"] != launch.platform.as_str()
    {
        return None;
    }
    let anchors: serde_json::Value = serde_json::from_str(ANCHORS).ok()?;
    let key_id = manifest["signature"]["key_id"].as_str()?;
    let cert = anchors["certificates"]
        .as_array()?
        .iter()
        .find(|c| c["key_id"].as_str() == Some(key_id))?;
    // This separate executable trust check runs before Command::spawn, on every restart.
    if cert["purpose"] != "updater" {
        return None;
    }
    let root_id = cert["root_key_id"].as_str()?;
    let root = root_for(&anchors, root_id, launch.environment.as_str())?;
    let held = revocations(data, &anchors, launch.environment.as_str())?;
    if revoked(&held, key_id) || revoked(&held, root_id) {
        return None;
    }
    ed25519(
        root["public_key"].as_str()?,
        cert["signature"].as_str()?,
        &unsigned(cert)?,
    )?;
    let signed_at = utc_time(manifest["created_at"].as_str()?)?;
    for key in [cert, root] {
        if signed_at < utc_time(key["not_before"].as_str()?)?
            || signed_at >= utc_time(key["not_after"].as_str()?)?
        {
            return None;
        }
    }
    ed25519(
        cert["public_key"].as_str()?,
        manifest["signature"]["value"].as_str()?,
        &unsigned(&manifest)?,
    )?;
    Some(manifest)
}

fn local_file(root: &Path, relative: &str) -> Option<PathBuf> {
    let path = Path::new(relative);
    if path
        .components()
        .any(|c| !matches!(c, std::path::Component::Normal(_)))
    {
        return None;
    }
    let mut file = root.to_path_buf();
    for part in path.components() {
        file.push(part);
        if fs::symlink_metadata(&file).ok()?.file_type().is_symlink() {
            return None;
        }
    }
    (file.is_file() && fs::canonicalize(&file).ok()?.starts_with(root)).then_some(file)
}

fn verified_program(launch: &VoiceStart, stop: &AtomicBool, data: &Path) -> Option<PathBuf> {
    let manifest = signed_manifest(launch, data)?;
    let root = fs::canonicalize(&launch.pack_dir).ok()?;
    let profile = &manifest["profiles"][launch.hardware.as_str()];
    let relative = profile["sidecar_path"].as_str()?;
    let entry = manifest["files"].as_array()?.iter().find(|file| {
        file["path"].as_str() == Some(relative)
            && file["role"] == "sidecar"
            && file["classes"]
                .as_array()
                .is_some_and(|c| c.contains(&serde_json::Value::from(launch.hardware.as_str())))
    })?;
    if entry["sha256"].as_str()? != launch.program_sha256 {
        return None;
    }
    let program = local_file(&root, relative)?;
    if fs::canonicalize(&launch.program).ok()? != program {
        return None;
    }
    if !program.starts_with(root)
        || fs::symlink_metadata(&launch.program)
            .ok()?
            .file_type()
            .is_symlink()
    {
        return None;
    }
    let mut input = File::open(&program).ok()?;
    if input.metadata().ok()?.len() > 512 * 1024 * 1024 {
        return None;
    }
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        if stop.load(Ordering::Acquire) {
            return None;
        }
        let count = input.read(&mut buffer).ok()?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let found = format!("{:x}", digest.finalize());
    (found == launch.program_sha256).then_some(program)
}

fn first_reply(reader: &mut impl BufRead) -> Option<Ready> {
    let mut line = Vec::new();
    loop {
        let buffer = reader.fill_buf().ok()?;
        if buffer.is_empty() {
            return None;
        }
        let newline = buffer.iter().position(|b| *b == b'\n');
        let count = newline.unwrap_or(buffer.len());
        if line.len() + count > 4096 {
            return None;
        }
        line.extend_from_slice(&buffer[..count]);
        reader.consume(count + usize::from(newline.is_some()));
        if newline.is_some() {
            return serde_json::from_slice(&line).ok();
        }
    }
}

fn end(child: &mut Child) {
    #[cfg(unix)]
    {
        use nix::sys::signal::{Signal, killpg};
        use nix::unistd::Pid;
        let _ = killpg(Pid::from_raw(child.id() as i32), Signal::SIGTERM);
    }
    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline {
        if matches!(child.try_wait(), Ok(Some(_))) {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    #[cfg(unix)]
    {
        use nix::sys::signal::{Signal, killpg};
        use nix::unistd::Pid;
        let _ = killpg(Pid::from_raw(child.id() as i32), Signal::SIGKILL);
    }
    let _ = child.kill();
    let _ = child.wait();
}

/// Programs a test bundle's script needs to run inside the profile; a build's sidecar is one frozen binary.
#[cfg(test)]
const INTERPRETERS: &[&str] = &["/bin/sh", "/bin/bash"];
#[cfg(not(test))]
const INTERPRETERS: &[&str] = &[];

/// A private, per-launch folder: the sidecar's home and temporary folder, and the only place it may write.
fn scratch_folder() -> Option<PathBuf> {
    let base = std::env::temp_dir().canonicalize().ok()?;
    let folder = base.join(format!("jana-voice-{}", &Token::new().reveal()[..24]));
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(&folder).ok()?;
    Some(folder)
}

/// Whether this platform can start the sidecar in this build: a release on macOS or Linux needs its wrapper.
fn sandbox_available(release: bool) -> bool {
    let probe = std::env::temp_dir();
    voice_sandbox::wrap(Path::new("/"), &probe, &probe, release, &[]).is_some()
}

fn launch_once(
    launch: &VoiceStart,
    pid_file: &Path,
    stop: &AtomicBool,
    send: &impl Fn(ToCore),
) -> Option<()> {
    let data = pid_file.parent()?.parent()?;
    let program = verified_program(launch, stop, data)?;
    let pack = fs::canonicalize(&launch.pack_dir).ok()?;
    let scratch = scratch_folder()?;
    let result = run(launch, pid_file, stop, send, &program, &pack, &scratch);
    let _ = fs::remove_dir_all(&scratch);
    result
}

#[allow(clippy::too_many_arguments)]
fn run(
    launch: &VoiceStart,
    pid_file: &Path,
    stop: &AtomicBool,
    send: &impl Fn(ToCore),
    program: &Path,
    pack: &Path,
    scratch: &Path,
) -> Option<()> {
    let interpreters: Vec<&Path> = INTERPRETERS.iter().map(Path::new).collect();
    let wrapped = voice_sandbox::wrap(
        program,
        pack,
        scratch,
        !cfg!(debug_assertions),
        &interpreters,
    )?;
    let token = Token::new();
    let mut command = Command::new(&wrapped.program);
    command
        .args(&wrapped.args)
        .current_dir(pack)
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if cfg!(windows) {
        for name in ["USERPROFILE", "SYSTEMROOT", "WINDIR"] {
            if let Some(value) = std::env::var_os(name) {
                command.env(name, value);
            }
        }
    }
    // The scratch folder is the sidecar's home and temporary folder: it never reads or writes the user's own.
    for name in ["HOME", "TMPDIR", "TMP", "TEMP"] {
        command.env(name, scratch);
    }
    command
        .env("HF_HUB_OFFLINE", "1")
        .env("TRANSFORMERS_OFFLINE", "1");
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command.spawn().ok()?;
    crate::orphans::track(pid_file, child.id());
    // Keep stdin open: the launcher treats EOF as parent loss. Neither credential enters argv/env/a file.
    let mut stdin = child.stdin.take();
    let input = serde_json::json!({"protocol": 1, "pack_dir": launch.pack_dir, "hardware": launch.hardware,
        "platform": launch.platform, "app_version": launch.app_version, "environment": launch.environment,
        "adapter_url": launch.adapter_url, "adapter_token": launch.adapter_token.reveal(), "realtime_token": token.reveal()});
    let configured = stdin.as_mut().is_some_and(|pipe| {
        serde_json::to_writer(&mut *pipe, &input)
            .and_then(|()| pipe.write_all(b"\n").map_err(serde_json::Error::io))
            .is_ok()
            && pipe.flush().is_ok()
    });
    if !configured {
        end(&mut child);
        return None;
    }
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            end(&mut child);
            return None;
        }
    };
    let (sender, receiver) = mpsc::sync_channel(1);
    let reader = thread::spawn(move || {
        let _ = sender.send(first_reply(&mut BufReader::new(stdout)));
    });
    let deadline = Instant::now() + Duration::from_secs(90);
    let mut ready = false;
    loop {
        if stop.load(Ordering::Acquire) || matches!(child.try_wait(), Ok(Some(_)) | Err(_)) {
            break;
        }
        if !ready {
            match receiver.try_recv() {
                Ok(Some(reply))
                    if reply.kind == "voice.ready" && reply.protocol == 1 && reply.port != 0 =>
                {
                    send(ToCore::VoiceEndpoint(VoiceEndpoint {
                        request_id: launch.request_id.clone(),
                        url: format!("ws://127.0.0.1:{}/v1/realtime", reply.port),
                        token: Redacted::new(token.reveal()),
                    }));
                    ready = true;
                }
                Ok(_) | Err(mpsc::TryRecvError::Disconnected) => break,
                Err(mpsc::TryRecvError::Empty) => {}
            }
            if Instant::now() > deadline {
                break;
            }
        }
        thread::sleep(Duration::from_millis(25));
    }
    drop(stdin);
    end(&mut child);
    let _ = reader.join();
    let _ = fs::remove_file(pid_file);
    Some(())
}

fn supervise(launch: VoiceStart, pid_file: &Path, stop: Arc<AtomicBool>, send: impl Fn(ToCore)) {
    crate::orphans::recover(pid_file);
    if !sandbox_available(!cfg!(debug_assertions)) {
        // A release without the platform's sandbox (Linux without bubblewrap) never starts the sidecar; retrying
        // cannot help, so the core hears at once and reads aloud through the OS synthesiser instead.
        send(ToCore::VoiceFailed(VoiceFailed {
            request_id: launch.request_id.clone(),
            code: VoiceFailedCode::VoiceGaveUp,
        }));
        return;
    }
    let mut crashes = Vec::new();
    while !stop.load(Ordering::Acquire) {
        let _ = launch_once(&launch, pid_file, &stop, &send);
        if stop.load(Ordering::Acquire) {
            return;
        }
        let now = Instant::now();
        crashes.retain(|time| now.duration_since(*time) < Duration::from_secs(300));
        crashes.push(now);
        if crashes.len() >= 2 {
            send(ToCore::VoiceFailed(VoiceFailed {
                request_id: launch.request_id.clone(),
                code: VoiceFailedCode::VoiceGaveUp,
            }));
            return;
        }
        let retry = Instant::now() + Duration::from_secs(2);
        while Instant::now() < retry && !stop.load(Ordering::Acquire) {
            thread::sleep(Duration::from_millis(25));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::control::{VoiceStartEnvironment, VoiceStartHardware, VoiceStartPlatform};

    #[test]
    fn reply_is_bounded_and_strict() {
        assert!(
            first_reply(&mut &b"{\"type\":\"voice.ready\",\"protocol\":1,\"port\":1234}\n"[..])
                .is_some()
        );
        assert!(first_reply(&mut vec![b'a'; 4097].as_slice()).is_none());
        assert!(first_reply(&mut &b"{\"type\":\"voice.ready\",\"protocol\":1,\"port\":1234,\"token\":\"secret\"}\n"[..]).is_none());
    }

    #[test]
    fn endpoint_debug_never_prints_credentials() {
        let endpoint = VoiceEndpoint {
            request_id: "test".into(),
            url: "ws://127.0.0.1:1234/v1/realtime".into(),
            token: Redacted::new("private-canary"),
        };
        assert!(!format!("{endpoint:?}").contains("private-canary"));
    }

    #[cfg(unix)]
    fn fake_bundle(body: &str) -> (PathBuf, VoiceStart) {
        use std::os::unix::fs::PermissionsExt;
        let directory =
            std::env::temp_dir().join(format!("jana-voice-test-{}", Token::new().reveal()));
        fs::create_dir(&directory).unwrap();
        let program = directory.join("voice");
        let bytes = format!("#!/bin/sh\n{body}\n");
        fs::write(&program, bytes.as_bytes()).unwrap();
        fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
        let launch = VoiceStart {
            request_id: "a".repeat(32),
            program: program.to_string_lossy().into_owned(),
            program_sha256: format!("{:x}", Sha256::digest(bytes.as_bytes())),
            pack_dir: directory.to_string_lossy().into_owned(),
            hardware: VoiceStartHardware::Mid,
            platform: VoiceStartPlatform::MacosAarch64,
            app_version: "0.0.0".into(),
            environment: VoiceStartEnvironment::Dev,
            adapter_url: "http://127.0.0.1:1234/v1/voice/llm".into(),
            adapter_token: Redacted::new("private-adapter-canary"),
        };
        sign_test_manifest(&launch, "updater");
        (directory, launch)
    }

    #[cfg(unix)]
    fn sign_test_manifest(launch: &VoiceStart, purpose: &str) {
        let mut manifest = serde_json::json!({"created_at": "2026-10-14T00:00:00.000Z",
            "platform": launch.platform, "profiles": {"mid": {"sidecar_path": "voice"}},
            "files": [{"path": "voice", "role": "sidecar", "classes": ["mid"], "sha256": launch.program_sha256}]});
        let phrase = format!(
            "jana development test signing root: never trusted by pilot or production builds: {purpose} intermediate"
        );
        let seed = Sha256::digest(phrase.as_bytes());
        let mut der = vec![
            0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22,
            0x04, 0x20,
        ];
        der.extend_from_slice(&seed);
        let key = rustls::pki_types::PrivatePkcs8KeyDer::from(der);
        let signer = rustls::crypto::ring::sign::any_supported_type(&key.into()).unwrap();
        let sig = signer
            .choose_scheme(&[rustls::SignatureScheme::ED25519])
            .unwrap()
            .sign(&canonical(&manifest).unwrap())
            .unwrap();
        // A tiny encoder for synthetic test signatures only.
        let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut encoded = String::new();
        for chunk in sig.chunks(3) {
            let value = (u32::from(chunk[0]) << 16)
                | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
                | u32::from(*chunk.get(2).unwrap_or(&0));
            for i in 0..4 {
                encoded.push(if i > chunk.len() {
                    '='
                } else {
                    alphabet[((value >> (18 - 6 * i)) & 63) as usize] as char
                });
            }
        }
        manifest["signature"] = serde_json::json!({"alg": "ed25519", "key_id": format!("key_dev_{purpose}"), "value": encoded});
        fs::write(
            Path::new(&launch.pack_dir).join("manifest.json"),
            canonical(&manifest).unwrap(),
        )
        .unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn executable_pack_needs_an_updater_signature_before_spawn() {
        let (directory, mut launch) = fake_bundle("exit 1");
        let stop = AtomicBool::new(false);
        assert!(verified_program(&launch, &stop, &directory).is_some());
        let revoked = r#"{"kind":"revocation_list","version":2,"created_at":"2026-10-13T00:00:00.000Z","revoked":[{"key_id":"key_dev_updater","revoked_at":"2026-10-15T00:00:00.000Z","reason":"synthetic test"}],"signature":{"alg":"ed25519","key_id":"key_root_test","value":"Ewt3B5IGW2E7zJTKYqby09uEX4cp1UulMxCs6ErVGQZmfImd4Ovmi5U0lLF8745JgVzb6ejqy6J2f7/5b1JpBg=="}}"#;
        // The list the core adopted, at its spec path (SEC-16), and where earlier builds kept it.
        fs::create_dir_all(directory.join("config")).unwrap();
        fs::write(directory.join("config/revocations.json"), revoked).unwrap();
        assert!(verified_program(&launch, &stop, &directory).is_none());
        fs::remove_file(directory.join("config/revocations.json")).unwrap();
        assert!(verified_program(&launch, &stop, &directory).is_some());
        fs::write(directory.join("revocation_list.json"), revoked).unwrap();
        assert!(verified_program(&launch, &stop, &directory).is_none());
        fs::remove_file(directory.join("revocation_list.json")).unwrap();
        sign_test_manifest(&launch, "model");
        assert!(verified_program(&launch, &stop, &directory).is_none());
        sign_test_manifest(&launch, "updater");
        launch.environment = VoiceStartEnvironment::Production;
        assert!(verified_program(&launch, &stop, &directory).is_none());
        launch.environment = VoiceStartEnvironment::Dev;
        fs::write(&launch.program, "tampered").unwrap();
        assert!(verified_program(&launch, &stop, &directory).is_none());
        fs::remove_dir_all(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn bundle_receives_secrets_only_on_stdin_and_stops_with_its_owner() {
        let (directory, launch) = fake_bundle(
            r#"
[ "$#" = 0 ] || exit 91
IFS= read -r config || exit 92
case "$config" in *private-adapter-canary*) ;; *) exit 93 ;; esac
export -p > "$TMPDIR/environment" || exit 95
while IFS= read -r line; do case "$line" in *private-adapter-canary*) exit 94 ;; esac; done < "$TMPDIR/environment"
printf '{"type":"voice.ready","protocol":1,"port":2345}\n'
while IFS= read -r command; do :; done
"#,
        );
        assert!(!format!("{launch:?}").contains("private-adapter-canary"));
        let (sender, receiver) = mpsc::channel();
        let pid_file = directory.join("pid.json");
        let worker = VoiceSupervisor::start(launch, pid_file.clone(), move |event| {
            let _ = sender.send(event);
        });
        let event = receiver.recv_timeout(Duration::from_secs(3)).unwrap();
        assert!(matches!(event, ToCore::VoiceEndpoint(_)));
        let started = Instant::now();
        drop(worker);
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(!pid_file.exists());
        fs::remove_dir_all(directory).unwrap();
    }

    /// VOC-23, SEC-06's mechanism on macOS: inside its Seatbelt profile the sidecar reaches loopback only, writes
    /// only its scratch folder (its home), reads nothing of the user's, and starts no process. The bundle reports
    /// ready only when every escape failed.
    #[cfg(target_os = "macos")]
    #[test]
    fn test_voc23_sidecar_sandbox_escape() {
        let home = PathBuf::from(std::env::var_os("HOME").unwrap()).join(".jana-voice-sentinel");
        fs::write(&home, b"private").unwrap();
        let (directory, launch) = fake_bundle(&format!(
            r#"
IFS= read -r config || exit 92
case "$HOME" in */jana-voice-*) ;; *) exit 81 ;; esac
[ "$HOME" = "$TMPDIR" ] || exit 82
echo ok > "$HOME/allowed" || exit 83
read -r secret < "{home}" && exit 84
echo x > "$PWD/escaped" && exit 85
exec 3<>/dev/tcp/1.1.1.1/53 && exit 86
printf '{{"type":"voice.ready","protocol":1,"port":2345}}\n'
while IFS= read -r command; do :; done
"#,
            home = home.display()
        ));
        let (sender, receiver) = mpsc::channel();
        let worker = VoiceSupervisor::start(launch, directory.join("pid.json"), move |event| {
            let _ = sender.send(event);
        });
        let event = receiver.recv_timeout(Duration::from_secs(10));
        drop(worker);
        let _ = fs::remove_file(&home);
        assert!(matches!(event, Ok(ToCore::VoiceEndpoint(_))), "{event:?}");
        assert!(!directory.join("escaped").exists());
        fs::remove_dir_all(directory).unwrap();
    }

    /// The profile also refuses a new process: a bundle that forks never reports ready.
    #[cfg(target_os = "macos")]
    #[test]
    fn test_voc23_sidecar_cannot_start_processes() {
        let (directory, launch) = fake_bundle(
            r#"
IFS= read -r config || exit 92
/usr/bin/true
printf '{"type":"voice.ready","protocol":1,"port":2345}\n'
while IFS= read -r command; do :; done
"#,
        );
        let (sender, receiver) = mpsc::channel();
        let worker = VoiceSupervisor::start(launch, directory.join("pid.json"), move |event| {
            let _ = sender.send(event);
        });
        let event = receiver.recv_timeout(Duration::from_secs(10));
        drop(worker);
        assert!(
            matches!(event, Ok(ToCore::VoiceFailed(_))),
            "a forking bundle gives up instead of starting: {event:?}"
        );
        fs::remove_dir_all(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn repeated_failure_gives_up_after_two_crashes() {
        let (directory, launch) = fake_bundle("exit 1");
        let (sender, receiver) = mpsc::channel();
        let started = Instant::now();
        let worker = VoiceSupervisor::start(launch, directory.join("pid.json"), move |event| {
            let _ = sender.send(event);
        });
        let event = receiver.recv_timeout(Duration::from_secs(5)).unwrap();
        assert!(matches!(
            event,
            ToCore::VoiceFailed(VoiceFailed {
                code: VoiceFailedCode::VoiceGaveUp,
                ..
            })
        ));
        assert!(started.elapsed() >= Duration::from_secs(2));
        drop(worker);
        fs::remove_dir_all(directory).unwrap();
    }
}
