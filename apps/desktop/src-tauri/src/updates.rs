//! Update checks (PLT-14, PLT-16, OPS-08): when and what the shell asks the update service.
//!
//! A check is made only while the adult has `update_checks` on and the network is usable, at most once per
//! `UPDATE_CHECK_INTERVAL_H`. It goes through the shared egress policy ([`net::check`], feature `update_checks`,
//! payload class `update_check`) and sends exactly the app version, the channel and the OS family: no device id, no
//! licence, no bucket (the rollout bucket is compared on the device, OPS-08). With `update_checks` off nothing is sent,
//! ever; the app keeps its installed version and takes updates from USB (`.janaupdate`, verified by the core).
//!
//! The response names the newest release for the channel with its signed update manifest and a `rollout_fraction`;
//! the device offers the update only when its local bucket is inside that fraction. The Tauri updater (owner item:
//! the `tauri-plugin-updater` dependency) downloads and verifies the installer's updater signature before any file is
//! written; the core checks channel and version (SEC-15) and stages it to install at quit (PLT-15).

use crate::generated::keys;
use crate::net::{self, Allowed, Limits, Refusal, Request, ResolvedPolicy};
use serde::Serialize;
use serde_json::Value;

const HOUR_MS: f64 = 3_600_000.0;

/// The whole body of an update check (PLT-14): nothing else is sent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CheckBody {
    pub app_version: String,
    pub channel: String,
    pub os_family: String,
}

/// When the next check is due.
#[derive(Debug, Clone)]
pub struct Scheduler {
    pub interval_ms: u64,
    last_ms: Option<u64>,
}

impl Default for Scheduler {
    fn default() -> Self {
        Scheduler {
            interval_ms: (keys::UPDATE_CHECK_INTERVAL_H * HOUR_MS) as u64,
            last_ms: None,
        }
    }
}

impl Scheduler {
    /// The check to make now, already allowed by the policy, or `None`: not due, `update_checks` off or not shipped,
    /// or the network unusable. A refusal is returned so the caller can emit its `blocked` notice; while the feature is
    /// off no request is even attempted.
    pub fn due(
        &mut self,
        now_ms: u64,
        policy: &ResolvedPolicy,
        limits: &Limits,
        url: &str,
        body: &CheckBody,
    ) -> Option<Result<(Allowed, Vec<u8>), Refusal>> {
        let on = policy
            .features
            .get("update_checks")
            .is_some_and(|f| f.enabled);
        if !on {
            return None;
        }
        if self
            .last_ms
            .is_some_and(|last| now_ms.saturating_sub(last) < self.interval_ms)
        {
            return None;
        }
        let bytes = serde_json::to_vec(body).unwrap_or_default();
        let request = Request {
            feature: "update_checks".into(),
            method: "POST".into(),
            url: url.into(),
            payload_class: "update_check".into(),
            body_len: bytes.len() as u64,
            carries_credential: false,
            download_len: None,
        };
        match net::check(policy, &request, limits) {
            Ok(allowed) => {
                self.last_ms = Some(now_ms);
                Some(Ok((allowed, bytes)))
            }
            // Offline: try again at the next tick, not a whole interval later.
            Err(refusal) if refusal.reason == net::RefusalReason::NetworkUnavailable => None,
            Err(refusal) => Some(Err(refusal)),
        }
    }
}

/// OPS-08: the device offers an update when its local bucket (a random number in [0, 1) made at install and never
/// sent) is inside the published `rollout_fraction`.
pub fn offered(response: &Value, bucket: f64) -> bool {
    response["rollout_fraction"]
        .as_f64()
        .is_some_and(|fraction| {
            bucket.is_finite()
                && (0.0..1.0).contains(&bucket)
                && fraction.is_finite()
                && (0.0..=1.0).contains(&fraction)
                && bucket < fraction
        })
}

/// OPS-08: the install bucket stays in local storage and is absent from CheckBody.
pub fn device_bucket(path: &std::path::Path) -> std::io::Result<f64> {
    use std::io::{Error, ErrorKind, Write};
    fn parse(text: &str) -> std::io::Result<f64> {
        let value: f64 = text
            .trim()
            .parse()
            .map_err(|_| Error::new(ErrorKind::InvalidData, "invalid rollout bucket"))?;
        if !value.is_finite() || !(0.0..1.0).contains(&value) {
            return Err(Error::new(ErrorKind::InvalidData, "invalid rollout bucket"));
        }
        Ok(value)
    }
    match std::fs::read_to_string(path) {
        Ok(text) => return parse(&text),
        Err(error) if error.kind() == ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let mut bytes = [0u8; 8];
    getrandom::fill(&mut bytes).map_err(|_| Error::other("rollout entropy unavailable"))?;
    // Use the exact integer range of an IEEE-754 double so rounding never creates 1.
    let bucket = (u64::from_le_bytes(bytes) >> 11) as f64 / (1u64 << 53) as f64;
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    match options.open(path) {
        Ok(mut file) => {
            write!(file, "{bucket}")?;
            file.sync_all()?;
            Ok(bucket)
        }
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            parse(&std::fs::read_to_string(path)?)
        }
        Err(error) => Err(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const URL: &str = "https://updates.dev.jana.invalid/v1/check";

    fn policy(update_checks: bool, network: &str) -> ResolvedPolicy {
        ResolvedPolicy::from_json(
            &json!({
                "version": 1, "environment": "dev", "release": false, "network": network,
                "features": {
                    "update_checks": {"enabled": update_checks, "hosts": ["updates.dev.jana.invalid"],
                                      "payload_classes": ["update_check"], "authenticated": false,
                                      "destination_label": "Update check", "data_classes": []},
                    "downloads": {"enabled": true, "hosts": ["downloads.dev.jana.invalid"],
                                  "payload_classes": ["download_request"], "authenticated": false,
                                  "destination_label": "Downloads", "data_classes": []},
                },
                "pins": {},
            })
            .to_string(),
        )
        .unwrap()
    }

    fn body() -> CheckBody {
        CheckBody {
            app_version: "1.0.0".into(),
            channel: "stable".into(),
            os_family: "windows".into(),
        }
    }

    const LIMITS: Limits = Limits {
        metered_large_download_bytes: 1_000_000,
    };

    /// PLT-14: with `update_checks` off, no update request is made over a 24-hour run (downloads on, network
    /// online); with it on, one check per interval, carrying only version, channel and OS family.
    #[test]
    fn plt14_no_checks_when_off() {
        let minute = 60_000;
        let day = 24 * 60 * minute;
        let mut off = Scheduler::default();
        let mut sent = 0;
        for now in (0..=day).step_by(minute as usize) {
            if off
                .due(now, &policy(false, "online"), &LIMITS, URL, &body())
                .is_some()
            {
                sent += 1;
            }
        }
        assert_eq!(
            sent, 0,
            "no update request in 24 hours with update_checks off"
        );

        let mut on = Scheduler {
            interval_ms: 6 * 60 * minute,
            last_ms: None,
        };
        let mut checks = vec![];
        for now in (0..day).step_by(minute as usize) {
            if let Some(Ok((allowed, bytes))) =
                on.due(now, &policy(true, "online"), &LIMITS, URL, &body())
            {
                checks.push((allowed, bytes));
            }
        }
        assert_eq!(checks.len(), 4, "one check per interval");
        let sent: Value = serde_json::from_slice(&checks[0].1).unwrap();
        let mut keys: Vec<&str> = sent
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        keys.sort_unstable();
        assert_eq!(keys, ["app_version", "channel", "os_family"]);
        assert_eq!(checks[0].0.ledger_entry(0).payload_class, "update_check");

        let mut offline = Scheduler::default();
        assert!(
            offline
                .due(0, &policy(true, "offline"), &LIMITS, URL, &body())
                .is_none()
        );
        assert!(
            offline
                .due(1, &policy(true, "online"), &LIMITS, URL, &body())
                .is_some(),
            "back online, the check is not deferred by a whole interval"
        );
    }

    #[test]
    fn rollout_bucket_is_compared_on_the_device() {
        let response = json!({"version": "1.1.0", "rollout_fraction": 0.1});
        assert!(offered(&response, 0.05));
        assert!(!offered(&response, 0.5));
        assert!(!offered(&json!({}), 0.0));
    }

    #[test]
    fn persisted_bucket_stays_local() {
        let root = std::env::temp_dir().join(format!("jana-m24-bucket-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("bucket");
        let first = device_bucket(&path).unwrap();
        assert!((0.0..1.0).contains(&first));
        assert_eq!(first, device_bucket(&path).unwrap());
        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn invalid_bucket_or_fraction_is_refused() {
        assert!(!offered(&json!({"rollout_fraction": 1.1}), 0.5));
        assert!(!offered(&json!({"rollout_fraction": 1.0}), -0.1));
        assert!(!offered(&json!({"rollout_fraction": 1.0}), f64::NAN));
    }
}
