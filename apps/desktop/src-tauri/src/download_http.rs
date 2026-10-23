//! Anonymous ranged HTTPS downloads. OS trust, host policy and SPKI pins are checked before request bytes.
use crate::downloads::{FetchError, Transport};
use crate::generated::keys;
use crate::net::{self, Limits, Request, ResolvedPolicy};
use reqwest::{Client, StatusCode, header};
use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
use rustls::{DigitallySignedStruct, RootCertStore, SignatureScheme};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;

pub type Policy = Arc<RwLock<ResolvedPolicy>>;
pub type Events = Arc<dyn Fn(&net::Allowed, net::NoticeState) + Send + Sync>;

pub fn snapshot(policy: &Policy) -> ResolvedPolicy {
    policy.read().unwrap_or_else(|p| p.into_inner()).clone()
}

#[derive(Debug)]
struct PinnedVerifier {
    policy: Policy,
    ordinary: Arc<dyn ServerCertVerifier>,
    provider: Arc<rustls::crypto::CryptoProvider>,
    rejected: Arc<AtomicBool>,
}

impl ServerCertVerifier for PinnedVerifier {
    fn verify_server_cert(
        &self,
        leaf: &CertificateDer<'_>,
        intermediates: &[CertificateDer<'_>],
        name: &ServerName<'_>,
        ocsp: &[u8],
        now: UnixTime,
    ) -> Result<ServerCertVerified, rustls::Error> {
        let result = (|| {
            self.ordinary
                .verify_server_cert(leaf, intermediates, name, ocsp, now)?;
            let policy = snapshot(&self.policy);
            let host = name.to_str();
            let certificates = std::iter::once(leaf)
                .chain(intermediates.iter())
                .collect::<Vec<_>>();
            let spki = certificates
                .iter()
                .map(|cert| {
                    webpki::EndEntityCert::try_from(*cert)
                        .map(|parsed| parsed.subject_public_key_info().as_ref().to_vec())
                        .map_err(|_| rustls::Error::General("invalid service certificate".into()))
                })
                .collect::<Result<Vec<_>, _>>()?;
            net::verify_pins(&policy, &host, &spki)
                .map_err(|_| rustls::Error::General("service certificate pin rejected".into()))?;
            // The same lookup as `verify_pins`: a fully qualified `host.` must not skip the second path below.
            let pins = net::pins_for(&policy, &host);
            if !pins.is_empty() {
                // A matching certificate appended to an unrelated chain must not satisfy a pin.
                // Verify a second path from the leaf to the matching CA after ordinary OS trust succeeds.
                let mut anchors = RootCertStore::empty();
                for (cert, key) in certificates.iter().zip(&spki) {
                    if pins.iter().any(|p| p.trim() == net::spki_pin(key)) {
                        anchors.add((*cert).clone())?;
                    }
                }
                let pinned = rustls::client::WebPkiServerVerifier::builder_with_provider(
                    Arc::new(anchors),
                    self.provider.clone(),
                )
                .build()
                .map_err(|_| rustls::Error::General("invalid pin anchors".into()))?;
                pinned.verify_server_cert(leaf, intermediates, name, ocsp, now)?;
            }
            Ok(ServerCertVerified::assertion())
        })();
        if result.is_err() {
            self.rejected.store(true, Ordering::SeqCst);
        }
        result
    }

    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        signature: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        let result = self
            .ordinary
            .verify_tls12_signature(message, cert, signature);
        if result.is_err() {
            self.rejected.store(true, Ordering::SeqCst);
        }
        result
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        signature: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        let result = self
            .ordinary
            .verify_tls13_signature(message, cert, signature);
        if result.is_err() {
            self.rejected.store(true, Ordering::SeqCst);
        }
        result
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.ordinary.supported_verify_schemes()
    }
}

/// The bytes of a chunk received before its connection dropped, stalled or was paused: the next fetch of the same
/// range asks only for the rest (PLT-11 range resume), so a slow link never refetches what already arrived.
struct Partial {
    url: String,
    offset: u64,
    len: u64,
    bytes: Vec<u8>,
}

pub struct Https {
    client: Client,
    partial: Option<Partial>,
    runtime: tokio::runtime::Runtime,
    policy: Policy,
    interrupted: Arc<AtomicBool>,
    stopped: Arc<AtomicBool>,
    file_bytes: u64,
    allow_metered: bool,
    events: Events,
    active: Mutex<Option<net::Allowed>>,
    rejected: Arc<AtomicBool>,
}

impl Https {
    pub fn new(
        policy: Policy,
        interrupted: Arc<AtomicBool>,
        stopped: Arc<AtomicBool>,
    ) -> Result<Self, String> {
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let verifier =
            rustls_platform_verifier::Verifier::new(provider.clone()).map_err(|e| e.to_string())?;
        Self::with_verifier(
            policy,
            interrupted,
            stopped,
            provider,
            Arc::new(verifier),
            Duration::from_secs_f64(keys::DOWNLOAD_REQUEST_TIMEOUT_S),
        )
    }

    /// `idle` bounds how long the connection may stay silent (waiting for the response or between body reads), never
    /// the whole transfer: a chunk on a slow but live link always completes.
    fn with_verifier(
        policy: Policy,
        interrupted: Arc<AtomicBool>,
        stopped: Arc<AtomicBool>,
        provider: Arc<rustls::crypto::CryptoProvider>,
        ordinary: Arc<dyn ServerCertVerifier>,
        idle: Duration,
    ) -> Result<Self, String> {
        let rejected = Arc::new(AtomicBool::new(false));
        let verifier = Arc::new(PinnedVerifier {
            policy: policy.clone(),
            ordinary,
            provider: provider.clone(),
            rejected: rejected.clone(),
        });
        let mut tls = rustls::ClientConfig::builder_with_provider(provider)
            .with_safe_default_protocol_versions()
            .map_err(|e| e.to_string())?
            .dangerous()
            .with_custom_certificate_verifier(verifier)
            .with_no_client_auth();
        // Each request rechecks the current trust and pin policy, including after policy changes.
        tls.resumption = rustls::client::Resumption::disabled();
        let client = Client::builder()
            .tls_backend_preconfigured(tls)
            .no_proxy()
            .http1_only()
            .pool_max_idle_per_host(0)
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs_f64(keys::NET_CONNECT_TIMEOUT_S))
            .read_timeout(idle)
            .build()
            .map_err(|e| e.to_string())?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())?;
        Ok(Self {
            client,
            partial: None,
            runtime,
            policy,
            interrupted,
            stopped,
            file_bytes: 0,
            allow_metered: false,
            events: Arc::new(|_, _| {}),
            active: Mutex::new(None),
            rejected,
        })
    }

    pub fn file_size(&mut self, bytes: u64) {
        self.file_bytes = bytes;
    }

    pub fn allow_metered(&mut self, allowed: bool) {
        self.allow_metered = allowed;
    }

    fn request_limits(&self) -> Limits {
        let mut configured = limits();
        if self.allow_metered {
            configured.metered_large_download_bytes = u64::MAX;
        }
        configured
    }

    pub fn events(&mut self, events: Events) {
        self.events = events;
    }

    fn end_request(&self, state: net::NoticeState) {
        if let Some(allowed) = self.active.lock().unwrap_or_else(|p| p.into_inner()).take() {
            (self.events)(&allowed, state);
        }
    }

    fn request(&self, url: &str) -> Request {
        Request {
            feature: "downloads".into(),
            method: "GET".into(),
            url: url.into(),
            payload_class: "download_request".into(),
            body_len: 0,
            carries_credential: false,
            download_len: Some(self.file_bytes),
        }
    }

    fn allowed(&self, url: &str) -> bool {
        !self.interrupted.load(Ordering::SeqCst)
            && !self.stopped.load(Ordering::SeqCst)
            && net::check(
                &snapshot(&self.policy),
                &self.request(url),
                &self.request_limits(),
            )
            .is_ok()
    }

    /// Fill `have` with the `len` bytes at `offset`, after whatever it already holds. A connection that drops or
    /// stalls after delivering new bytes is resumed at once from the new offset; one that delivered nothing ends the
    /// fetch (the item waits for the network) and `have` is kept for the next fetch of this range.
    async fn range(
        &self,
        url: &str,
        offset: u64,
        len: u64,
        have: &mut Vec<u8>,
    ) -> Result<(), FetchError> {
        loop {
            let before = have.len();
            match self.resume(url, offset, len, have).await {
                Err(FetchError::ConnectionLost) if have.len() > before => {
                    self.end_request(net::NoticeState::Ended);
                }
                other => return other,
            }
        }
    }

    /// One request for the part of the range not yet in `have`, following allowed redirects.
    async fn resume(
        &self,
        url: &str,
        offset: u64,
        len: u64,
        have: &mut Vec<u8>,
    ) -> Result<(), FetchError> {
        let end = offset
            .checked_add(len)
            .and_then(|v| v.checked_sub(1))
            .ok_or(FetchError::Status(416))?;
        let start = offset.saturating_add(have.len() as u64);
        if start > end {
            return if have.len() as u64 == len {
                Ok(())
            } else {
                Err(FetchError::Status(413))
            };
        }
        let mut current = url.to_string();
        for _ in 0..=keys::DOWNLOAD_REDIRECT_MAX {
            if !self.allowed(&current) {
                return Err(FetchError::ConnectionLost);
            }
            let policy = snapshot(&self.policy);
            let allowed = net::check(&policy, &self.request(&current), &self.request_limits())
                .map_err(|_| FetchError::ConnectionLost)?;
            if net::verify_pins(&policy, &allowed.host, &[]) == Err(net::PinFailure::Unpinned) {
                (self.events)(&allowed, net::NoticeState::Blocked);
                return Err(FetchError::Refused("certificate_pins_missing".into()));
            }
            (self.events)(&allowed, net::NoticeState::Started);
            *self.active.lock().unwrap_or_else(|p| p.into_inner()) = Some(allowed);
            let mut response = self
                .client
                .get(&current)
                .header(header::RANGE, format!("bytes={start}-{end}"))
                .header(header::ACCEPT_ENCODING, "identity")
                .send()
                .await
                .map_err(classify)?;
            if response.status().is_redirection() {
                self.end_request(net::NoticeState::Ended);
                let location = response
                    .headers()
                    .get(header::LOCATION)
                    .and_then(|h| h.to_str().ok())
                    .ok_or(FetchError::Status(response.status().as_u16()))?;
                current =
                    net::check_redirect(&snapshot(&self.policy), "downloads", &current, location)
                        .map_err(|_| FetchError::Status(403))?;
                continue;
            }
            let full_file =
                response.status() == StatusCode::OK && start == 0 && len == self.file_bytes;
            if response.status() != StatusCode::PARTIAL_CONTENT && !full_file {
                return Err(FetchError::Status(response.status().as_u16()));
            }
            if !full_file {
                let expected = format!("bytes {start}-{end}/{}", self.file_bytes);
                if response
                    .headers()
                    .get(header::CONTENT_RANGE)
                    .and_then(|h| h.to_str().ok())
                    != Some(expected.as_str())
                {
                    return Err(FetchError::Status(416));
                }
            }
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|_| FetchError::ConnectionLost)?
            {
                if !self.allowed(&current) {
                    return Err(FetchError::ConnectionLost);
                }
                if (have.len() as u64).saturating_add(chunk.len() as u64) > len {
                    return Err(FetchError::Status(413));
                }
                have.extend_from_slice(&chunk);
            }
            return if have.len() as u64 == len {
                Ok(())
            } else {
                Err(FetchError::ConnectionLost)
            };
        }
        Err(FetchError::Status(310))
    }
}

pub fn limits() -> Limits {
    Limits {
        metered_large_download_bytes: keys::DOWNLOAD_METERED_LARGE_MB as u64 * 1024 * 1024,
    }
}

impl Transport for Https {
    fn fetch(&mut self, url: &str, offset: u64, len: u64) -> Result<Vec<u8>, FetchError> {
        self.rejected.store(false, Ordering::SeqCst);
        let mut have = self
            .partial
            .take()
            .filter(|p| p.url == url && p.offset == offset && p.len == len)
            .map(|p| p.bytes)
            .unwrap_or_default();
        let result = self.runtime.block_on(async {
            tokio::select! {
                result = self.range(url, offset, len, &mut have) => result,
                _ = async {
                    while self.allowed(url) {
                        tokio::time::sleep(Duration::from_millis(keys::DOWNLOAD_CONTROL_POLL_MS as u64)).await;
                    }
                } => Err(FetchError::ConnectionLost),
            }
        });
        let result = if self.rejected.load(Ordering::SeqCst) {
            Err(FetchError::Refused("certificate_rejected".into()))
        } else {
            result
        };
        self.end_request(if matches!(result, Err(FetchError::Refused(_))) {
            net::NoticeState::Blocked
        } else {
            net::NoticeState::Ended
        });
        match result {
            Ok(()) => Ok(have),
            Err(error) => {
                if error == FetchError::ConnectionLost && !have.is_empty() {
                    self.partial = Some(Partial {
                        url: url.into(),
                        offset,
                        len,
                        bytes: have,
                    });
                }
                Err(error)
            }
        }
    }
}

fn classify(error: reqwest::Error) -> FetchError {
    let mut source: Option<&(dyn std::error::Error + 'static)> = Some(&error);
    while let Some(cause) = source {
        if cause.downcast_ref::<rustls::Error>().is_some() {
            return FetchError::Refused("certificate_rejected".into());
        }
        if cause
            .downcast_ref::<std::io::Error>()
            .and_then(|e| e.get_ref())
            .is_some_and(|e| e.is::<rustls::Error>())
        {
            return FetchError::Refused("certificate_rejected".into());
        }
        source = cause.source();
    }
    FetchError::ConnectionLost
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::{BufRead, BufReader};
    use std::path::{Path, PathBuf};
    use std::process::{Child, Command, Stdio};
    use std::time::Instant;

    struct Server {
        child: Child,
        folder: PathBuf,
        url: String,
        policy: Policy,
    }
    impl Server {
        fn start(name: &str) -> Self {
            let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
            let python = root.join(if cfg!(windows) {
                ".venv/Scripts/python.exe"
            } else {
                ".venv/bin/python"
            });
            let folder =
                std::env::temp_dir().join(format!("jana-https-{name}-{}", std::process::id()));
            fs::create_dir_all(&folder).unwrap();
            let mut child = Command::new(python)
                .arg(
                    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/download_server.py"),
                )
                .arg(&folder)
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            let mut line = String::new();
            BufReader::new(child.stdout.take().unwrap())
                .read_line(&mut line)
                .unwrap();
            let port = serde_json::from_str::<serde_json::Value>(&line).unwrap()["port"]
                .as_u64()
                .unwrap();
            let url = format!("https://localhost:{port}");
            let policy = ResolvedPolicy::from_json(&serde_json::json!({
                "version": 1, "release": true, "environment": "production", "network": "online",
                "features": { "downloads": { "enabled": true, "hosts": [format!("localhost:{port}")],
                    "payload_classes": ["download_request"], "authenticated": false,
                    "destination_label": "Models", "data_classes": [] } },
                "pins": { "localhost": [net::spki_pin(&fs::read(folder.join("root.spki")).unwrap())] }
            }).to_string()).unwrap();
            Self {
                child,
                folder,
                url,
                policy: Arc::new(RwLock::new(policy)),
            }
        }
        fn http(&self, interrupted: Arc<AtomicBool>) -> Https {
            self.http_idle(
                interrupted,
                Duration::from_secs_f64(keys::DOWNLOAD_REQUEST_TIMEOUT_S),
            )
        }
        fn http_idle(&self, interrupted: Arc<AtomicBool>, idle: Duration) -> Https {
            let provider = Arc::new(rustls::crypto::ring::default_provider());
            let mut roots = RootCertStore::empty();
            roots
                .add(CertificateDer::from(
                    fs::read(self.folder.join("root.der")).unwrap(),
                ))
                .unwrap();
            let ordinary = rustls::client::WebPkiServerVerifier::builder_with_provider(
                Arc::new(roots),
                provider.clone(),
            )
            .build()
            .unwrap();
            let mut http = Https::with_verifier(
                self.policy.clone(),
                interrupted,
                Arc::new(AtomicBool::new(false)),
                provider,
                ordinary,
                idle,
            )
            .unwrap();
            http.file_size(8);
            http
        }
        fn ranges(&self) -> Vec<String> {
            self.requests()
                .iter()
                .map(|r| {
                    r["headers"]["range"]
                        .as_str()
                        .unwrap_or_default()
                        .to_string()
                })
                .collect()
        }
        fn requests(&self) -> Vec<serde_json::Value> {
            fs::read_to_string(self.folder.join("requests.jsonl"))
                .unwrap_or_default()
                .lines()
                .map(|s| serde_json::from_str(s).unwrap())
                .collect()
        }
    }
    impl Drop for Server {
        fn drop(&mut self) {
            let _ = self.child.kill();
            let _ = self.child.wait();
            let _ = fs::remove_dir_all(&self.folder);
        }
    }

    #[test]
    fn https_ranges_redirects_and_pin_failures() {
        let server = Server::start("ranges");
        let mut http = server.http(Arc::new(AtomicBool::new(false)));
        assert_eq!(
            http.fetch(&format!("{}/file", server.url), 2, 3),
            Ok(b"cde".to_vec())
        );
        assert_eq!(
            http.fetch(&format!("{}/redirect", server.url), 0, 4),
            Ok(b"abcd".to_vec())
        );
        assert_eq!(
            http.fetch(&format!("{}/bad-range", server.url), 0, 4),
            Err(FetchError::Status(416))
        );
        assert_eq!(
            http.fetch(&format!("{}/outside", server.url), 0, 4),
            Err(FetchError::Status(403))
        );
        let requests = server.requests();
        assert_eq!(requests.len(), 5);
        assert_eq!(requests[0]["headers"]["range"], "bytes=2-4");
        for row in requests {
            assert!(row["headers"].as_object().unwrap().keys().all(|k| matches!(
                k.to_lowercase().as_str(),
                "host" | "range" | "accept" | "accept-encoding" | "connection" | "content-length"
            )));
        }
        // Wrong and missing pins reject before any HTTP headers reach the server.
        server
            .policy
            .write()
            .unwrap()
            .pins
            .insert("localhost".into(), vec![net::spki_pin(b"other CA")]);
        let refused = http.fetch(&format!("{}/file", server.url), 0, 4);
        assert!(
            matches!(refused, Err(FetchError::Refused(_))),
            "{refused:?}"
        );
        server.policy.write().unwrap().pins.clear();
        assert_eq!(
            http.fetch(&format!("{}/file", server.url), 0, 4),
            Err(FetchError::Refused("certificate_pins_missing".into()))
        );
        assert_eq!(server.requests().len(), 5);
    }

    #[test]
    fn pause_and_policy_off_interrupt_in_flight_https() {
        for turn_off in [false, true] {
            let server = Server::start(if turn_off { "off" } else { "pause" });
            let interrupted = Arc::new(AtomicBool::new(false));
            let mut http = server.http(interrupted.clone());
            let url = format!("{}/slow", server.url);
            let worker = std::thread::spawn(move || http.fetch(&url, 0, 4));
            let start = Instant::now();
            while server.requests().is_empty() && start.elapsed() < Duration::from_secs(2) {
                std::thread::sleep(Duration::from_millis(10));
            }
            assert_eq!(server.requests().len(), 1);
            if turn_off {
                server
                    .policy
                    .write()
                    .unwrap()
                    .features
                    .get_mut("downloads")
                    .unwrap()
                    .enabled = false;
            } else {
                interrupted.store(true, Ordering::SeqCst);
            }
            assert_eq!(worker.join().unwrap(), Err(FetchError::ConnectionLost));
            assert!(start.elapsed() < Duration::from_secs(2));
        }
    }

    /// PLT-11: the time limit is for silence, not for the transfer. A chunk on a slow but live link (here one byte
    /// every 100 ms, twice the idle limit in all) completes in one request instead of being cut and fetched again.
    #[test]
    fn test_plt11_slow_link_completes_chunk() {
        let server = Server::start("throttled");
        let mut http =
            server.http_idle(Arc::new(AtomicBool::new(false)), Duration::from_millis(400));
        let started = Instant::now();
        assert_eq!(
            http.fetch(&format!("{}/throttled", server.url), 0, 8),
            Ok(b"abcdefgh".to_vec())
        );
        assert!(started.elapsed() > Duration::from_millis(400));
        assert_eq!(server.ranges(), ["bytes=0-7"]);
    }

    /// PLT-11 range resume inside a chunk: a connection that stalls past the idle limit or drops after delivering
    /// part of the range is resumed from the first missing byte, never from the chunk's start.
    #[test]
    fn test_plt11_stalled_or_dropped_chunk_resumes_from_partial_offset() {
        for path in ["stall-half", "drop-half"] {
            let server = Server::start(path);
            let mut http =
                server.http_idle(Arc::new(AtomicBool::new(false)), Duration::from_millis(500));
            assert_eq!(
                http.fetch(&format!("{}/{path}", server.url), 0, 8),
                Ok(b"abcdefgh".to_vec()),
                "{path}"
            );
            assert_eq!(server.ranges(), ["bytes=0-7", "bytes=4-7"], "{path}");
        }
    }

    /// A pause in the middle of a chunk keeps the bytes already received; resuming asks only for the rest.
    #[test]
    fn test_plt11_pause_keeps_partial_chunk() {
        let server = Server::start("pause-partial");
        let interrupted = Arc::new(AtomicBool::new(false));
        let mut http = server.http_idle(interrupted.clone(), Duration::from_secs(10));
        let url = format!("{}/stall-half", server.url);
        let worker = std::thread::spawn(move || {
            let result = http.fetch(&url, 0, 8);
            (http, url, result)
        });
        let start = Instant::now();
        while server.requests().is_empty() && start.elapsed() < Duration::from_secs(2) {
            std::thread::sleep(Duration::from_millis(10));
        }
        std::thread::sleep(Duration::from_millis(300)); // the first half arrives, then the server stalls
        interrupted.store(true, Ordering::SeqCst);
        let (mut http, url, paused) = worker.join().unwrap();
        assert_eq!(paused, Err(FetchError::ConnectionLost));
        interrupted.store(false, Ordering::SeqCst);
        assert_eq!(http.fetch(&url, 0, 8), Ok(b"abcdefgh".to_vec()));
        assert_eq!(server.ranges(), ["bytes=0-7", "bytes=4-7"]);
        // A different range never reuses those bytes.
        assert_eq!(
            http.fetch(&format!("{}/file", server.url), 2, 3),
            Ok(b"cde".to_vec())
        );
    }

    /// Accepts every chain, so only the pin checks decide.
    #[derive(Debug)]
    struct AnyChain(Arc<rustls::crypto::CryptoProvider>);
    impl ServerCertVerifier for AnyChain {
        fn verify_server_cert(
            &self,
            _: &CertificateDer<'_>,
            _: &[CertificateDer<'_>],
            _: &ServerName<'_>,
            _: &[u8],
            _: UnixTime,
        ) -> Result<ServerCertVerified, rustls::Error> {
            Ok(ServerCertVerified::assertion())
        }
        fn verify_tls12_signature(
            &self,
            _: &[u8],
            _: &CertificateDer<'_>,
            _: &DigitallySignedStruct,
        ) -> Result<HandshakeSignatureValid, rustls::Error> {
            Ok(HandshakeSignatureValid::assertion())
        }
        fn verify_tls13_signature(
            &self,
            _: &[u8],
            _: &CertificateDer<'_>,
            _: &DigitallySignedStruct,
        ) -> Result<HandshakeSignatureValid, rustls::Error> {
            Ok(HandshakeSignatureValid::assertion())
        }
        fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
            self.0.signature_verification_algorithms.supported_schemes()
        }
    }

    /// ARC-06 pins: the fully qualified spelling of a pinned host (`localhost.`) gets the same checks, including the
    /// second path from the leaf to the pinned CA, so a pinned CA appended to an unrelated chain is refused.
    #[test]
    fn pinned_host_with_trailing_dot_keeps_the_pinned_path() {
        let server = Server::start("dot");
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let verifier = PinnedVerifier {
            policy: server.policy.clone(),
            ordinary: Arc::new(AnyChain(provider.clone())),
            provider,
            rejected: Arc::new(AtomicBool::new(false)),
        };
        let read = |name: &str| CertificateDer::from(fs::read(server.folder.join(name)).unwrap());
        let (root, leaf, stray) = (read("root.der"), read("leaf.der"), read("stray.der"));
        for host in ["localhost", "localhost.", "LOCALHOST."] {
            let name = ServerName::try_from(host.to_string()).unwrap();
            assert!(
                verifier
                    .verify_server_cert(
                        &stray,
                        std::slice::from_ref(&root),
                        &name,
                        &[],
                        UnixTime::now()
                    )
                    .is_err(),
                "{host}: a stray leaf in front of the pinned CA"
            );
        }
        let name = ServerName::try_from("localhost").unwrap();
        assert!(
            verifier
                .verify_server_cert(
                    &leaf,
                    std::slice::from_ref(&root),
                    &name,
                    &[],
                    UnixTime::now()
                )
                .is_ok()
        );
    }
}
