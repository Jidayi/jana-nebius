//! The shell's enforcement point of the connectivity layer (ARC-06): downloads and update checks.
//!
//! The core resolves the shared policy table (`services/agent-core/agent_core/net/policy.json`) with the adult
//! switches and the environment, and hands the shell the resolved document. Every request the shell's transport
//! makes (M20.b) goes through [`check`] first, every redirect through [`check_redirect`] and every TLS handshake
//! through [`verify_pins`]. An allowed request yields a ledger entry (ARC-10) and the `egress.notice` events the
//! shell hands the core for the app channel (API-15); a refused one yields a `blocked` notice and nothing leaves.
//!
//! What is refused: a feature other than `downloads` and `update_checks` (those belong to `agent_core.net`), a
//! feature that is off or not shipped (ARC-07, PRV-02), a host outside the feature's allow-list or a disallowed
//! payload class (ARC-06), anything but HTTPS and redirects off the allow-list (SEC-31), any request carrying the
//! service credential or a device identifier (SEC-21), any request while the network is `off`, `offline` or
//! `limited`, and large downloads while `metered` (ARC-08). This module holds no HTTP or TLS client.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fmt;

/// The features this enforcement point serves (ARC-06); every other feature of TABLE ARC-07a is `agent_core.net`'s.
pub const SHELL_FEATURES: [&str; 2] = ["downloads", "update_checks"];

/// The resolved-policy document version this module understands.
pub const POLICY_VERSION: u32 = 1;

const HTTPS_PORT: u16 = 443;
/// The payload class of a file fetch, the only kind the metered rule pauses (ARC-08, PLT-11).
const DOWNLOAD_PAYLOAD_CLASS: &str = "download_request";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Environment {
    Dev,
    Staging,
    Pilot,
    Production,
}

/// TABLE ARC-08a, plus `unknown` before the first check (API-15).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Network {
    Off,
    Offline,
    Limited,
    Metered,
    Online,
    Unknown,
}

/// One feature of the resolved policy. Only features whose stage the build ships appear.
#[derive(Debug, Clone, Deserialize)]
pub struct FeaturePolicy {
    pub enabled: bool,
    pub hosts: Vec<String>,
    pub payload_classes: Vec<String>,
    pub authenticated: bool,
    pub destination_label: String,
    pub data_classes: Vec<String>,
}

/// The policy the core resolves and hands the shell (both enforcement points share it, ARC-06).
#[derive(Debug, Clone, Deserialize)]
pub struct ResolvedPolicy {
    pub version: u32,
    pub environment: Environment,
    pub release: bool,
    pub network: Network,
    pub features: BTreeMap<String, FeaturePolicy>,
    /// Host -> base64 SHA-256 of the SubjectPublicKeyInfo of each pinned CA key (SEC-31).
    #[serde(default)]
    pub pins: BTreeMap<String, Vec<String>>,
}

#[derive(Debug)]
pub enum PolicyError {
    Json(serde_json::Error),
    Version(u32),
}

impl ResolvedPolicy {
    /// Parses the core's document; an unknown version is refused rather than guessed at (fail closed).
    pub fn from_json(text: &str) -> Result<ResolvedPolicy, PolicyError> {
        let policy: ResolvedPolicy = serde_json::from_str(text).map_err(PolicyError::Json)?;
        if policy.version != POLICY_VERSION {
            return Err(PolicyError::Version(policy.version));
        }
        Ok(policy)
    }

    /// The policy before the core has sent one: every feature off, nothing leaves (PRV-02).
    pub fn all_off() -> ResolvedPolicy {
        ResolvedPolicy {
            version: POLICY_VERSION,
            environment: Environment::Production,
            release: true,
            network: Network::Off,
            features: BTreeMap::new(),
            pins: BTreeMap::new(),
        }
    }
}

/// Limits from the configuration, never literals in the logic. The transport builds this from the generated
/// shell keys (ARC-28) once the metered threshold is declared there.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Limits {
    /// A download at least this large pauses while the connection is metered (ARC-08).
    pub metered_large_download_bytes: u64,
}

/// One request the transport wants to make.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub feature: String,
    pub method: String,
    pub url: String,
    pub payload_class: String,
    /// Bytes the request sends (its body).
    pub body_len: u64,
    /// Whether the request carries the service credential or any other device identifier (SEC-21).
    pub carries_credential: bool,
    /// For a file fetch, the size of the file from its signed manifest; `None` when not known.
    pub download_len: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RefusalReason {
    /// The feature is switched off, or the build does not ship it (ARC-07, PRV-02).
    FeatureOff,
    /// The feature is not one the shell enforces (ARC-06).
    FeatureNotShell,
    HostNotAllowed,
    PayloadClassNotAllowed,
    /// Plain HTTP (SEC-31).
    PlainHttp,
    /// A URL with another scheme, user info, an unusual host or characters the module will not reason about.
    UnsupportedUrl,
    /// The network is `off`, `offline` or `limited` (ARC-08).
    NetworkUnavailable,
    /// A large download while the connection is metered (ARC-08).
    MeteredLargeDownload,
    /// Downloads and update checks never send the service credential or a device identifier (SEC-21).
    CredentialOnAnonymousFeature,
}

impl RefusalReason {
    /// A stable code for the shell's log.
    pub fn code(self) -> &'static str {
        match self {
            RefusalReason::FeatureOff => "feature_off",
            RefusalReason::FeatureNotShell => "feature_not_shell",
            RefusalReason::HostNotAllowed => "host_not_allowed",
            RefusalReason::PayloadClassNotAllowed => "payload_class_not_allowed",
            RefusalReason::PlainHttp => "plain_http",
            RefusalReason::UnsupportedUrl => "unsupported_url",
            RefusalReason::NetworkUnavailable => "network_unavailable",
            RefusalReason::MeteredLargeDownload => "metered_large_download",
            RefusalReason::CredentialOnAnonymousFeature => "credential_on_anonymous_feature",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub feature: String,
    pub reason: RefusalReason,
}

impl fmt::Display for Refusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "egress refused: feature {} ({})",
            self.feature,
            self.reason.code()
        )
    }
}

impl Refusal {
    /// The `blocked` notice for the app channel (API-15), for a shell feature the policy lists; `None` otherwise
    /// (a feature the shell does not serve is a programming error, not a learner-visible attempt).
    pub fn blocked_notice(&self, policy: &ResolvedPolicy) -> Option<Value> {
        if !SHELL_FEATURES.contains(&self.feature.as_str()) {
            return None;
        }
        let feature = policy.features.get(&self.feature)?;
        Some(egress_notice(
            &self.feature,
            NoticeState::Blocked,
            &feature.destination_label,
            &feature.data_classes,
        ))
    }
}

/// A request the policy allows, with what the ledger and the notices need.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Allowed {
    pub feature: String,
    pub host: String,
    pub port: u16,
    pub payload_class: String,
    pub bytes: u64,
    pub destination_label: String,
    pub data_classes: Vec<String>,
}

/// One row of the egress ledger (ARC-10): time, feature, host, bytes and payload class, and never content.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct LedgerEntry {
    pub at_ms: u64,
    pub feature: String,
    pub destination: String,
    pub bytes: u64,
    pub payload_class: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NoticeState {
    Started,
    Ended,
    Blocked,
}

impl NoticeState {
    fn name(self) -> &'static str {
        match self {
            NoticeState::Started => "started",
            NoticeState::Ended => "ended",
            NoticeState::Blocked => "blocked",
        }
    }
}

impl Allowed {
    pub fn ledger_entry(&self, at_ms: u64) -> LedgerEntry {
        LedgerEntry {
            at_ms,
            feature: self.feature.clone(),
            destination: self.host.clone(),
            bytes: self.bytes,
            payload_class: self.payload_class.clone(),
        }
    }

    pub fn notice(&self, state: NoticeState) -> Value {
        egress_notice(
            &self.feature,
            state,
            &self.destination_label,
            &self.data_classes,
        )
    }
}

/// The `egress.notice` app event (API-15) as the shell hands it to the core.
pub fn egress_notice(
    feature: &str,
    state: NoticeState,
    destination_label: &str,
    data_classes: &[String],
) -> Value {
    json!({
        "type": "egress.notice",
        "feature": feature,
        "state": state.name(),
        "destination_label": destination_label,
        "data_classes": data_classes,
    })
}

/// Decides one request against the resolved policy (ARC-06, ARC-07, ARC-08, SEC-21, SEC-31).
pub fn check(
    policy: &ResolvedPolicy,
    request: &Request,
    limits: &Limits,
) -> Result<Allowed, Refusal> {
    let refuse = |reason| Refusal {
        feature: request.feature.clone(),
        reason,
    };
    let feature = shell_feature(policy, &request.feature).map_err(refuse)?;
    let url = parse_url(&request.url).map_err(refuse)?;
    if !host_allowed(feature, &url.host, url.port) {
        return Err(refuse(RefusalReason::HostNotAllowed));
    }
    if !feature
        .payload_classes
        .iter()
        .any(|c| c == &request.payload_class)
    {
        return Err(refuse(RefusalReason::PayloadClassNotAllowed));
    }
    if request.carries_credential {
        return Err(refuse(RefusalReason::CredentialOnAnonymousFeature));
    }
    match policy.network {
        Network::Off | Network::Offline | Network::Limited => {
            return Err(refuse(RefusalReason::NetworkUnavailable));
        }
        // A file of unknown size counts as large: the metered rule fails closed.
        Network::Metered
            if request.payload_class == DOWNLOAD_PAYLOAD_CLASS
                && request
                    .download_len
                    .is_none_or(|len| len >= limits.metered_large_download_bytes) =>
        {
            return Err(refuse(RefusalReason::MeteredLargeDownload));
        }
        // `unknown` is the state before the first check; the request itself then tells the layer.
        Network::Metered | Network::Online | Network::Unknown => {}
    }
    Ok(Allowed {
        feature: request.feature.clone(),
        host: url.host,
        port: url.port,
        payload_class: request.payload_class.clone(),
        bytes: request.body_len,
        destination_label: feature.destination_label.clone(),
        data_classes: feature.data_classes.clone(),
    })
}

/// Decides one redirect (SEC-31): the target must be HTTPS to a host on the same feature's allow-list. Returns the
/// absolute URL to follow.
pub fn check_redirect(
    policy: &ResolvedPolicy,
    feature: &str,
    from_url: &str,
    location: &str,
) -> Result<String, Refusal> {
    let refuse = |reason| Refusal {
        feature: feature.to_string(),
        reason,
    };
    let policy_feature = shell_feature(policy, feature).map_err(refuse)?;
    let from = parse_url(from_url).map_err(refuse)?;
    if !host_allowed(policy_feature, &from.host, from.port) {
        return Err(refuse(RefusalReason::HostNotAllowed));
    }
    let target = resolve_location(&from, location).map_err(refuse)?;
    let to = parse_url(&target).map_err(refuse)?;
    if !host_allowed(policy_feature, &to.host, to.port) {
        return Err(refuse(RefusalReason::HostNotAllowed));
    }
    Ok(target)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PinFailure {
    /// Pins are configured for the host and no certificate in the chain carries one of them.
    NoMatch,
    /// No pins are configured for the host and the build is a release, or a pilot or production one.
    Unpinned,
}

/// Certificate pinning for our services (SEC-31). `chain_spki` holds the DER SubjectPublicKeyInfo of each
/// certificate the peer presented, after ordinary chain validation. With pins for the host, one element must match;
/// without pins, only non-release dev and staging builds proceed, and everything else fails closed.
pub fn verify_pins(
    policy: &ResolvedPolicy,
    host: &str,
    chain_spki: &[Vec<u8>],
) -> Result<(), PinFailure> {
    let pins = pins_for(policy, host);
    if pins.is_empty() {
        let unpinned_ok = !policy.release
            && matches!(policy.environment, Environment::Dev | Environment::Staging);
        return if unpinned_ok {
            Ok(())
        } else {
            Err(PinFailure::Unpinned)
        };
    }
    let matched = chain_spki.iter().any(|spki| {
        let pin = spki_pin(spki);
        pins.iter().any(|p| p.trim() == pin)
    });
    if matched {
        Ok(())
    } else {
        Err(PinFailure::NoMatch)
    }
}

/// The SPKI pins the policy lists for `host`, matched as hosts are everywhere else: ignoring case and one trailing
/// dot. Every pin decision uses this one lookup, so a fully qualified spelling cannot skip a check.
pub fn pins_for<'p>(policy: &'p ResolvedPolicy, host: &str) -> &'p [String] {
    let host = normalise_host(host);
    policy
        .pins
        .iter()
        .find(|(h, _)| normalise_host(h) == host)
        .map(|(_, p)| p.as_slice())
        .unwrap_or_default()
}

/// The pin of a public key: base64 (RFC 4648, padded) of the SHA-256 of its DER SubjectPublicKeyInfo.
pub fn spki_pin(spki_der: &[u8]) -> String {
    base64_standard(&Sha256::digest(spki_der))
}

fn shell_feature<'p>(
    policy: &'p ResolvedPolicy,
    feature: &str,
) -> Result<&'p FeaturePolicy, RefusalReason> {
    if !SHELL_FEATURES.contains(&feature) {
        return Err(RefusalReason::FeatureNotShell);
    }
    match policy.features.get(feature) {
        Some(f) if f.enabled => Ok(f),
        _ => Err(RefusalReason::FeatureOff),
    }
}

fn host_allowed(feature: &FeaturePolicy, host: &str, port: u16) -> bool {
    feature
        .hosts
        .iter()
        .any(|entry| match parse_authority(entry.trim()) {
            Ok((h, p)) => h == host && p.unwrap_or(HTTPS_PORT) == port,
            Err(_) => false,
        })
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Url {
    host: String,
    port: u16,
    /// Path and query, without the fragment; at least "/".
    path_and_query: String,
}

/// Parses an absolute https URL without a URL crate. Anything unusual is refused rather than interpreted.
fn parse_url(raw: &str) -> Result<Url, RefusalReason> {
    if raw.bytes().any(|b| !b.is_ascii_graphic() || b == b'\\') {
        return Err(RefusalReason::UnsupportedUrl);
    }
    let (scheme, rest) = raw.split_once("://").ok_or(RefusalReason::UnsupportedUrl)?;
    if scheme.eq_ignore_ascii_case("http") {
        return Err(RefusalReason::PlainHttp);
    }
    if !scheme.eq_ignore_ascii_case("https") {
        return Err(RefusalReason::UnsupportedUrl);
    }
    let end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    let (authority, tail) = rest.split_at(end);
    let (host, port) = parse_authority(authority)?;
    let tail = tail.split('#').next().unwrap_or_default();
    let path_and_query = if tail.starts_with('/') {
        tail.to_string()
    } else {
        format!("/{tail}")
    };
    Ok(Url {
        host,
        port: port.unwrap_or(HTTPS_PORT),
        path_and_query,
    })
}

/// Host and optional port of an authority (`host`, `host:port`, `[v6]`, `[v6]:port`); user info is refused.
fn parse_authority(authority: &str) -> Result<(String, Option<u16>), RefusalReason> {
    if authority.contains('@') {
        return Err(RefusalReason::UnsupportedUrl);
    }
    let (host, port) = if let Some(inner) = authority.strip_prefix('[') {
        let (v6, after) = inner.split_once(']').ok_or(RefusalReason::UnsupportedUrl)?;
        if v6.is_empty()
            || !v6
                .chars()
                .all(|c| c.is_ascii_hexdigit() || c == ':' || c == '.')
        {
            return Err(RefusalReason::UnsupportedUrl);
        }
        let port = match after {
            "" => None,
            p => Some(p.strip_prefix(':').ok_or(RefusalReason::UnsupportedUrl)?),
        };
        (format!("[{}]", v6.to_ascii_lowercase()), port)
    } else {
        let (name, port) = match authority.split_once(':') {
            Some((n, p)) => (n, Some(p)),
            None => (authority, None),
        };
        let name = normalise_host(name);
        let label_ok =
            |l: &str| !l.is_empty() && l.chars().all(|c| c.is_ascii_alphanumeric() || c == '-');
        if !name.split('.').all(label_ok) {
            return Err(RefusalReason::UnsupportedUrl);
        }
        (name, port)
    };
    let port = match port {
        None => None,
        Some(p) => match p.parse::<u16>() {
            Ok(n) if n > 0 && p.chars().all(|c| c.is_ascii_digit()) => Some(n),
            _ => return Err(RefusalReason::UnsupportedUrl),
        },
    };
    Ok((host, port))
}

/// Lower case, without one trailing dot (the fully qualified spelling of the same name).
fn normalise_host(host: &str) -> String {
    let lower = host.to_ascii_lowercase();
    lower.strip_suffix('.').map(str::to_string).unwrap_or(lower)
}

/// The absolute URL a `Location` header points to, resolved against the URL that answered.
fn resolve_location(from: &Url, location: &str) -> Result<String, RefusalReason> {
    if location.is_empty()
        || location
            .bytes()
            .any(|b| !b.is_ascii_graphic() || b == b'\\')
    {
        return Err(RefusalReason::UnsupportedUrl);
    }
    if let Some(rest) = location.strip_prefix("//") {
        return Ok(format!("https://{rest}"));
    }
    let first_delimiter = location.find(['/', '?', '#']).unwrap_or(location.len());
    if location[..first_delimiter].contains(':') {
        return Ok(location.to_string()); // absolute; parse_url judges its scheme and host
    }
    let origin = if from.port == HTTPS_PORT {
        format!("https://{}", from.host)
    } else {
        format!("https://{}:{}", from.host, from.port)
    };
    let from_path = from.path_and_query.split('?').next().unwrap_or("/");
    let resolved = if location.starts_with('/') {
        format!("{origin}{location}")
    } else if location.starts_with('?') {
        format!("{origin}{from_path}{location}")
    } else if location.starts_with('#') {
        format!("{origin}{}", from.path_and_query)
    } else {
        let dir = &from_path[..from_path.rfind('/').map_or(0, |i| i + 1)];
        format!("{origin}{dir}{location}")
    };
    Ok(resolved)
}

/// Standard base64 with padding (RFC 4648 section 4), for pins; small enough not to warrant a dependency.
fn base64_standard(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(char::from(ALPHABET[((n >> (18 - 6 * i)) & 0x3f) as usize]));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// Documentation addresses (RFC 5737 TEST-NET-1, RFC 3849) on the discard port: only ever looked up in the routing
/// table, never sent to.
const ROUTE_HINT_V4: (std::net::Ipv4Addr, u16) = (std::net::Ipv4Addr::new(192, 0, 2, 1), 9);
const ROUTE_HINT_V6: (std::net::Ipv6Addr, u16) =
    (std::net::Ipv6Addr::new(0x2001, 0xdb8, 0, 0, 0, 0, 0, 1), 9);

/// The OS reachability hint the shell hands the core as `control.net_state` (ARC-08 "OS reports no route"): whether
/// the operating system has a route off this device. Connecting a UDP socket only consults the routing table; no
/// packet leaves, so this is not a probe and runs even while every feature is off. The core's connectivity layer
/// decides from it whether to probe an enabled feature's host.
pub fn os_route_hint() -> bool {
    use std::net::{Ipv4Addr, Ipv6Addr, SocketAddr, UdpSocket};
    let routes: [(SocketAddr, SocketAddr); 2] = [
        ((Ipv4Addr::UNSPECIFIED, 0).into(), ROUTE_HINT_V4.into()),
        ((Ipv6Addr::UNSPECIFIED, 0).into(), ROUTE_HINT_V6.into()),
    ];
    routes.iter().any(|(local, remote)| {
        UdpSocket::bind(local)
            .and_then(|socket| socket.connect(remote))
            .is_ok()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn route_hint_answers_without_sending() {
        // Whatever this machine's network, the lookup answers at once and never errors.
        let started = std::time::Instant::now();
        let _ = os_route_hint();
        assert!(started.elapsed() < std::time::Duration::from_secs(1));
    }

    const TABLE: &str = include_str!("../../../../services/agent-core/agent_core/net/policy.json");
    const TABLE_FEATURES: [&str; 10] = [
        "cloud_tier",
        "downloads",
        "update_checks",
        "cloud_backup",
        "multi_device",
        "parent_remote_view",
        "cloud_voice",
        "study_materials",
        "telemetry",
        "crash_reports",
    ];
    const DOWNLOADS_HOST: &str = "downloads.dev.jana.invalid";
    const UPDATES_HOST: &str = "updates.dev.jana.invalid";
    // Test values only; the shipped threshold comes from the configuration.
    const LIMITS: Limits = Limits {
        metered_large_download_bytes: 1000,
    };

    /// A resolved policy built from the shared table the way the core resolves it: the given environment's hosts,
    /// only the features the given stages ship, and the listed ones switched on.
    fn resolve(
        environment: &str,
        release: bool,
        network: &str,
        shipped: &[&str],
        enabled: &[&str],
    ) -> ResolvedPolicy {
        let table: Value = serde_json::from_str(TABLE).unwrap();
        let mut features = serde_json::Map::new();
        for (id, row) in table["features"].as_object().unwrap() {
            if !shipped.contains(&row["stage"].as_str().unwrap()) {
                continue;
            }
            let host = &table["services"][environment][row["service"].as_str().unwrap()];
            features.insert(
                id.clone(),
                json!({
                    "enabled": enabled.contains(&id.as_str()),
                    "hosts": [host],
                    "payload_classes": row["payload_classes"],
                    "authenticated": row["authenticated"],
                    "destination_label": row["destination_label"],
                    "data_classes": row["data_classes"],
                }),
            );
        }
        let document = json!({
            "version": 1,
            "environment": environment,
            "release": release,
            "network": network,
            "features": features,
            "pins": {},
        });
        ResolvedPolicy::from_json(&document.to_string()).unwrap()
    }

    fn dev(network: &str) -> ResolvedPolicy {
        resolve(
            "dev",
            false,
            network,
            &["S2"],
            &["downloads", "update_checks"],
        )
    }

    fn download(url: &str, len: Option<u64>) -> Request {
        Request {
            feature: "downloads".into(),
            method: "GET".into(),
            url: url.into(),
            payload_class: "download_request".into(),
            body_len: 0,
            carries_credential: false,
            download_len: len,
        }
    }

    fn update_check() -> Request {
        Request {
            feature: "update_checks".into(),
            method: "GET".into(),
            url: format!("https://{UPDATES_HOST}/v1/check?channel=stable"),
            payload_class: "update_check".into(),
            body_len: 120,
            carries_credential: false,
            download_len: None,
        }
    }

    fn reason(result: Result<Allowed, Refusal>) -> RefusalReason {
        result.unwrap_err().reason
    }

    #[test]
    fn policy_table_lists_exactly_the_online_features() {
        let table: Value = serde_json::from_str(TABLE).unwrap();
        let mut ids: Vec<&str> = table["features"]
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        ids.sort_unstable();
        let mut expected = TABLE_FEATURES.to_vec();
        expected.sort_unstable();
        assert_eq!(ids, expected);
        for id in SHELL_FEATURES {
            assert_eq!(
                table["features"][id]["authenticated"],
                json!(false),
                "{id} must be anonymous"
            );
            assert_eq!(
                table["features"][id]["data_classes"],
                json!([]),
                "{id} sends no learner data"
            );
        }
    }

    #[test]
    fn allowed_download_yields_ledger_entry_and_notices() {
        let policy = dev("online");
        let allowed = check(
            &policy,
            &download(
                &format!("https://{DOWNLOADS_HOST}/packs/maths.pack"),
                Some(5000),
            ),
            &LIMITS,
        )
        .unwrap();
        assert_eq!(allowed.host, DOWNLOADS_HOST);
        let entry = serde_json::to_value(allowed.ledger_entry(1_700_000_000_000)).unwrap();
        let mut keys: Vec<&str> = entry
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            ["at_ms", "bytes", "destination", "feature", "payload_class"]
        );
        assert_eq!(entry["destination"], DOWNLOADS_HOST);
        assert_eq!(entry["payload_class"], "download_request");
        assert_eq!(
            allowed.notice(NoticeState::Started),
            json!({"type": "egress.notice", "feature": "downloads", "state": "started",
                   "destination_label": "Downloads", "data_classes": []})
        );
        assert_eq!(allowed.notice(NoticeState::Ended)["state"], "ended");
    }

    #[test]
    fn update_check_is_allowed_and_counts_its_body() {
        let allowed = check(&dev("online"), &update_check(), &LIMITS).unwrap();
        assert_eq!(allowed.ledger_entry(1).bytes, 120);
        assert_eq!(allowed.destination_label, "Update check");
    }

    #[test]
    fn switched_off_or_unshipped_feature_is_refused() {
        let off = resolve("dev", false, "online", &["S2"], &["update_checks"]);
        let url = format!("https://{DOWNLOADS_HOST}/f");
        assert_eq!(
            reason(check(&off, &download(&url, Some(1)), &LIMITS)),
            RefusalReason::FeatureOff
        );
        let nothing = ResolvedPolicy::all_off();
        assert_eq!(
            reason(check(&nothing, &update_check(), &LIMITS)),
            RefusalReason::FeatureOff
        );
    }

    #[test]
    fn features_of_the_core_are_refused_by_the_shell() {
        let policy = resolve(
            "dev",
            false,
            "online",
            &["S2", "S4"],
            &["cloud_tier", "cloud_backup", "downloads"],
        );
        for feature in [
            "cloud_tier",
            "cloud_backup",
            "telemetry",
            "lan_compute",
            "unknown",
        ] {
            let mut request = download("https://gateway.dev.jana.invalid/v1/x", Some(1));
            request.feature = feature.into();
            assert_eq!(
                reason(check(&policy, &request, &LIMITS)),
                RefusalReason::FeatureNotShell,
                "{feature}"
            );
        }
    }

    #[test]
    fn host_off_the_allow_list_is_refused() {
        let policy = dev("online");
        for url in [
            format!("https://{UPDATES_HOST}/f"), // another feature's host
            "https://example.com/f".to_string(), // not ours
            format!("https://{DOWNLOADS_HOST}.example.com/f"),
            format!("https://{DOWNLOADS_HOST}:8443/f"), // allow-listed host, other port
            "https://10.0.0.5/f".to_string(),           // IP literal not on the list
            "https://[::1]/f".to_string(),
        ] {
            assert_eq!(
                reason(check(&policy, &download(&url, Some(1)), &LIMITS)),
                RefusalReason::HostNotAllowed,
                "{url}"
            );
        }
    }

    #[test]
    fn host_matching_ignores_case_and_a_trailing_dot() {
        let policy = dev("online");
        let url = "https://DOWNLOADS.dev.Jana.invalid./f";
        assert_eq!(
            check(&policy, &download(url, Some(1)), &LIMITS)
                .unwrap()
                .host,
            DOWNLOADS_HOST
        );
        let explicit_port = format!("https://{DOWNLOADS_HOST}:443/f");
        assert!(check(&policy, &download(&explicit_port, Some(1)), &LIMITS).is_ok());
    }

    #[test]
    fn allow_listed_ip_literal_and_port_entries_match_exactly() {
        let mut policy = dev("online");
        policy.features.get_mut("downloads").unwrap().hosts =
            vec!["192.0.2.7".into(), "[2001:db8::7]:8443".into()];
        assert!(check(&policy, &download("https://192.0.2.7/f", Some(1)), &LIMITS).is_ok());
        assert!(
            check(
                &policy,
                &download("https://[2001:DB8::7]:8443/f", Some(1)),
                &LIMITS
            )
            .is_ok()
        );
        let wrong_port = download("https://[2001:db8::7]/f", Some(1));
        assert_eq!(
            reason(check(&policy, &wrong_port, &LIMITS)),
            RefusalReason::HostNotAllowed
        );
    }

    #[test]
    fn payload_class_off_the_list_is_refused() {
        let mut request = update_check();
        request.payload_class = "telemetry_aggregate".into();
        assert_eq!(
            reason(check(&dev("online"), &request, &LIMITS)),
            RefusalReason::PayloadClassNotAllowed
        );
        let mut activation = download(&format!("https://{DOWNLOADS_HOST}/activate"), None);
        activation.payload_class = "licence_activation".into();
        activation.method = "POST".into();
        assert!(check(&dev("online"), &activation, &LIMITS).is_ok());
    }

    #[test]
    fn plain_http_and_odd_urls_are_refused() {
        let policy = dev("online");
        let cases = [
            (
                format!("http://{DOWNLOADS_HOST}/f"),
                RefusalReason::PlainHttp,
            ),
            (
                format!("HTTP://{DOWNLOADS_HOST}/f"),
                RefusalReason::PlainHttp,
            ),
            (
                format!("ftp://{DOWNLOADS_HOST}/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("wss://{DOWNLOADS_HOST}/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://user:pw@{DOWNLOADS_HOST}/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://evil.example@{DOWNLOADS_HOST}/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://{DOWNLOADS_HOST}:0/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://{DOWNLOADS_HOST}:99999/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://{DOWNLOADS_HOST}:+443/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://{DOWNLOADS_HOST}\\@evil.example/f"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                format!("https://{DOWNLOADS_HOST}/a b"),
                RefusalReason::UnsupportedUrl,
            ),
            (
                "https://downloads%2edev.jana.invalid/f".to_string(),
                RefusalReason::UnsupportedUrl,
            ),
            (
                "https://dównloads.dev.jana.invalid/f".to_string(),
                RefusalReason::UnsupportedUrl,
            ),
            ("https:///f".to_string(), RefusalReason::UnsupportedUrl),
            ("https://a..b/f".to_string(), RefusalReason::UnsupportedUrl),
            (DOWNLOADS_HOST.to_string(), RefusalReason::UnsupportedUrl),
        ];
        for (url, expected) in cases {
            assert_eq!(
                reason(check(&policy, &download(&url, Some(1)), &LIMITS)),
                expected,
                "{url}"
            );
        }
    }

    #[test]
    fn credential_is_never_sent_by_downloads_or_update_checks() {
        let mut request = update_check();
        request.carries_credential = true;
        assert_eq!(
            reason(check(&dev("online"), &request, &LIMITS)),
            RefusalReason::CredentialOnAnonymousFeature
        );
        // Even a policy that wrongly marks the feature authenticated cannot make it carry the credential.
        let mut policy = dev("online");
        policy
            .features
            .get_mut("update_checks")
            .unwrap()
            .authenticated = true;
        assert_eq!(
            reason(check(&policy, &request, &LIMITS)),
            RefusalReason::CredentialOnAnonymousFeature
        );
    }

    #[test]
    fn nothing_leaves_while_off_offline_or_limited() {
        let url = format!("https://{DOWNLOADS_HOST}/f");
        for network in ["off", "offline", "limited"] {
            let policy = dev(network);
            assert_eq!(
                reason(check(&policy, &update_check(), &LIMITS)),
                RefusalReason::NetworkUnavailable
            );
            assert_eq!(
                reason(check(&policy, &download(&url, Some(1)), &LIMITS)),
                RefusalReason::NetworkUnavailable
            );
        }
        for network in ["online", "unknown"] {
            assert!(
                check(&dev(network), &download(&url, Some(1)), &LIMITS).is_ok(),
                "{network}"
            );
        }
    }

    #[test]
    fn large_downloads_pause_while_metered() {
        let policy = dev("metered");
        let url = format!("https://{DOWNLOADS_HOST}/f");
        let threshold = LIMITS.metered_large_download_bytes;
        assert!(check(&policy, &download(&url, Some(threshold - 1)), &LIMITS).is_ok());
        for len in [Some(threshold), Some(threshold * 10), None] {
            assert_eq!(
                reason(check(&policy, &download(&url, len), &LIMITS)),
                RefusalReason::MeteredLargeDownload
            );
        }
        assert!(
            check(
                &dev("online"),
                &download(&url, Some(threshold * 10)),
                &LIMITS
            )
            .is_ok()
        );
        assert!(check(&policy, &update_check(), &LIMITS).is_ok());
    }

    #[test]
    fn refusal_gives_a_blocked_notice_for_shell_features_only() {
        let policy = resolve("dev", false, "offline", &["S2"], &["downloads"]);
        let refusal = check(
            &policy,
            &download(&format!("https://{DOWNLOADS_HOST}/f"), Some(1)),
            &LIMITS,
        )
        .unwrap_err();
        assert_eq!(
            refusal.blocked_notice(&policy).unwrap(),
            json!({"type": "egress.notice", "feature": "downloads", "state": "blocked",
                   "destination_label": "Downloads", "data_classes": []})
        );
        assert!(refusal.to_string().contains("network_unavailable"));
        let core = Refusal {
            feature: "cloud_tier".into(),
            reason: RefusalReason::FeatureNotShell,
        };
        assert!(core.blocked_notice(&policy).is_none());
    }

    #[test]
    fn policy_with_an_unknown_version_or_shape_is_rejected() {
        let mut document: Value = serde_json::from_str(
            r#"{"version": 1, "environment": "dev", "release": false, "network": "online", "features": {}}"#,
        )
        .unwrap();
        assert!(
            ResolvedPolicy::from_json(&document.to_string())
                .unwrap()
                .pins
                .is_empty()
        );
        document["version"] = json!(2);
        assert!(matches!(
            ResolvedPolicy::from_json(&document.to_string()),
            Err(PolicyError::Version(2))
        ));
        document["version"] = json!(1);
        document["network"] = json!("sideways");
        assert!(matches!(
            ResolvedPolicy::from_json(&document.to_string()),
            Err(PolicyError::Json(_))
        ));
    }

    #[test]
    fn redirects_stay_on_the_allow_list_and_on_https() {
        let policy = dev("online");
        let from = format!("https://{DOWNLOADS_HOST}/packs/v2/maths.pack?x=1");
        let ok = |location: &str| check_redirect(&policy, "downloads", &from, location).unwrap();
        assert_eq!(
            ok("/mirror/a.pack"),
            format!("https://{DOWNLOADS_HOST}/mirror/a.pack")
        );
        assert_eq!(
            ok("b.pack"),
            format!("https://{DOWNLOADS_HOST}/packs/v2/b.pack")
        );
        assert_eq!(
            ok("?part=2"),
            format!("https://{DOWNLOADS_HOST}/packs/v2/maths.pack?part=2")
        );
        assert_eq!(
            ok(&format!("//{DOWNLOADS_HOST}/c")),
            format!("https://{DOWNLOADS_HOST}/c")
        );
        assert_eq!(
            ok(&format!("https://{DOWNLOADS_HOST}/d")),
            format!("https://{DOWNLOADS_HOST}/d")
        );
        let refused = |location: &str| {
            check_redirect(&policy, "downloads", &from, location)
                .unwrap_err()
                .reason
        };
        assert_eq!(
            refused(&format!("http://{DOWNLOADS_HOST}/d")),
            RefusalReason::PlainHttp
        );
        assert_eq!(
            refused("https://cdn.example.com/d"),
            RefusalReason::HostNotAllowed
        );
        assert_eq!(
            refused("//cdn.example.com/d"),
            RefusalReason::HostNotAllowed
        );
        assert_eq!(
            refused(&format!("https://{UPDATES_HOST}/d")),
            RefusalReason::HostNotAllowed
        );
        assert_eq!(
            refused(&format!("https://x@{DOWNLOADS_HOST}/d")),
            RefusalReason::UnsupportedUrl
        );
        assert_eq!(
            refused("javascript:alert(1)"),
            RefusalReason::UnsupportedUrl
        );
        assert_eq!(refused(""), RefusalReason::UnsupportedUrl);
        let off_list_origin =
            check_redirect(&policy, "downloads", "https://cdn.example.com/a", "/b").unwrap_err();
        assert_eq!(off_list_origin.reason, RefusalReason::HostNotAllowed);
        let core = check_redirect(&policy, "cloud_tier", &from, "/b").unwrap_err();
        assert_eq!(core.reason, RefusalReason::FeatureNotShell);
    }

    #[test]
    fn redirect_keeps_a_non_default_allow_listed_port() {
        let mut policy = dev("online");
        policy.features.get_mut("downloads").unwrap().hosts =
            vec![format!("{DOWNLOADS_HOST}:8443")];
        let from = format!("https://{DOWNLOADS_HOST}:8443/a");
        let target = check_redirect(&policy, "downloads", &from, "/b").unwrap();
        assert_eq!(target, format!("https://{DOWNLOADS_HOST}:8443/b"));
    }

    #[test]
    fn base64_matches_rfc4648_vectors() {
        for (input, expected) in [
            ("", ""),
            ("f", "Zg=="),
            ("fo", "Zm8="),
            ("foo", "Zm9v"),
            ("foob", "Zm9vYg=="),
            ("fooba", "Zm9vYmE="),
            ("foobar", "Zm9vYmFy"),
        ] {
            assert_eq!(base64_standard(input.as_bytes()), expected);
        }
        assert_eq!(base64_standard(&[0xfb, 0xff, 0xbf]), "+/+/");
    }

    #[test]
    fn spki_pin_is_base64_sha256() {
        // SHA-256("abc"), FIPS 180-2 example.
        assert_eq!(
            spki_pin(b"abc"),
            "ungWv48Bz+pBQUDeXa4iI7ADYaOWF3qctBD/YfIAFa0="
        );
    }

    fn pinned(environment: &str, release: bool) -> ResolvedPolicy {
        let mut policy = resolve(environment, release, "online", &["S2"], &["downloads"]);
        policy.pins.insert(
            DOWNLOADS_HOST.into(),
            vec![spki_pin(b"intermediate"), spki_pin(b"backup")],
        );
        policy
    }

    #[test]
    fn pinned_host_needs_a_matching_key_in_the_chain() {
        let policy = pinned("dev", false);
        let leaf = b"leaf".to_vec();
        assert_eq!(
            verify_pins(
                &policy,
                DOWNLOADS_HOST,
                &[leaf.clone(), b"intermediate".to_vec()]
            ),
            Ok(())
        );
        assert_eq!(
            verify_pins(
                &policy,
                "Downloads.dev.jana.invalid.",
                &[leaf.clone(), b"backup".to_vec()]
            ),
            Ok(())
        );
        let intercepted = [leaf, b"proxy root".to_vec()];
        assert_eq!(
            verify_pins(&policy, DOWNLOADS_HOST, &intercepted),
            Err(PinFailure::NoMatch)
        );
        assert_eq!(
            verify_pins(&policy, DOWNLOADS_HOST, &[]),
            Err(PinFailure::NoMatch)
        );
        assert_eq!(
            verify_pins(&pinned("production", true), DOWNLOADS_HOST, &intercepted),
            Err(PinFailure::NoMatch)
        );
    }

    #[test]
    fn unpinned_host_passes_only_in_non_release_dev_and_staging() {
        let chain = [b"leaf".to_vec()];
        let unpinned = |environment: &str, release: bool| {
            let policy = resolve(environment, release, "online", &["S2"], &["downloads"]);
            verify_pins(&policy, DOWNLOADS_HOST, &chain)
        };
        assert_eq!(unpinned("dev", false), Ok(()));
        assert_eq!(unpinned("staging", false), Ok(()));
        assert_eq!(unpinned("dev", true), Err(PinFailure::Unpinned));
        assert_eq!(unpinned("pilot", false), Err(PinFailure::Unpinned));
        assert_eq!(unpinned("production", true), Err(PinFailure::Unpinned));
        let mut empty = resolve("production", true, "online", &["S2"], &["downloads"]);
        empty.pins.insert(DOWNLOADS_HOST.into(), vec![]);
        assert_eq!(
            verify_pins(&empty, DOWNLOADS_HOST, &chain),
            Err(PinFailure::Unpinned)
        );
        assert_eq!(
            verify_pins(&ResolvedPolicy::all_off(), DOWNLOADS_HOST, &chain),
            Err(PinFailure::Unpinned)
        );
    }
}
