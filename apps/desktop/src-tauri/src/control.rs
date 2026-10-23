//! The shell's side of the control channel (ARC-04, `contracts/control`): newline-delimited JSON on the agent
//! core's stdin and stdout. Secrets cross only this channel, never argv, the environment, files or logs.
//!
//! The frame types are generated from the control contract (`generated::control`, D39); this module adds only the
//! line framing.

pub use crate::generated::control::*;

/// This shell's control-channel version (ARC-29), from the contract's interface version.
pub const CONTROL_PROTOCOL: ProtocolVersion = PROTOCOL;

/// One line for the core's stdin.
pub fn line(message: &ToCore) -> String {
    let mut text = serde_json::to_string(message).unwrap_or_default();
    text.push('\n');
    text
}

/// A line from the core's stdout, if it is a control frame (anything else is ignored, never logged).
pub fn parse(line: &str) -> Option<ToShell> {
    serde_json::from_str(line.trim()).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::path::{Path, PathBuf};

    fn fixtures(kind: &str) -> Vec<(PathBuf, Value)> {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../evals/contracts/control/control")
            .join(kind);
        let mut found: Vec<_> = std::fs::read_dir(&dir)
            .unwrap_or_else(|e| panic!("{}: {e}", dir.display()))
            .map(|entry| entry.unwrap().path())
            .filter(|path| path.extension().is_some_and(|e| e == "json"))
            .map(|path| {
                let value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
                (path, value)
            })
            .collect();
        found.sort_by(|a, b| a.0.cmp(&b.0));
        assert!(!found.is_empty(), "no {kind} fixtures in {}", dir.display());
        found
    }

    /// A frame of either direction, re-serialised.
    fn round_trip(frame: &Value) -> Option<Value> {
        if let Ok(to_core) = serde_json::from_value::<ToCore>(frame.clone()) {
            return serde_json::to_value(to_core).ok();
        }
        serde_json::from_value::<ToShell>(frame.clone())
            .ok()
            .and_then(|to_shell| serde_json::to_value(to_shell).ok())
    }

    #[test]
    fn every_valid_fixture_round_trips() {
        for (path, frame) in fixtures("valid") {
            assert_eq!(
                round_trip(&frame).as_ref(),
                Some(&frame),
                "{}",
                path.display()
            );
        }
    }

    #[test]
    fn frames_with_unknown_fields_or_wrong_types_are_refused() {
        // The shape fixtures; value constraints (patterns, lengths) are the core's contract validators' to refuse.
        let shape = ["unknown_property.json", "wrong_type.json"];
        for (path, frame) in fixtures("invalid") {
            if path
                .file_name()
                .is_some_and(|name| shape.iter().any(|s| name == *s))
            {
                assert_eq!(round_trip(&frame), None, "{}", path.display());
            }
        }
        let refused = [
            r#"{"type":"control.hello","protocol":{"major":1,"minor":4},"extra":1}"#,
            r#"{"type":"control.hello","protocol":{"major":"1","minor":4}}"#,
            r#"{"type":"control.hello","protocol":{"major":1,"minor":4,"patch":0}}"#,
            r#"{"type":"control.keys","store":"os_keychain","entries":[{"ref":"jana.a","value":"x","more":1}]}"#,
            r#"{"type":"control.keys","store":"somewhere","entries":[]}"#,
            r#"{"type":"control.key_put","ref":"jana.device-db"}"#,
            r#"{"type":"control.ready","protocol":{"major":1,"minor":4},"api_port":"80","epoch":"0123456789abcdef"}"#,
            r#"{"type":"control.download_state","download_id":"dl_1","state":"lost","bytes_done":0,"bytes_total":0}"#,
            r#"{"type":"control.unknown"}"#,
            r#"{"protocol":{"major":1,"minor":4}}"#,
        ];
        for frame in refused {
            let value: Value = serde_json::from_str(frame).unwrap();
            assert_eq!(round_trip(&value), None, "{frame}");
        }
    }

    #[test]
    fn every_contract_frame_has_a_variant() {
        let schema: Value = serde_json::from_str(include_str!(
            "../../../../services/agent-core/agent_core/contracts/schemas/control/control.schema.json"
        ))
        .unwrap();
        for (union, generated) in [("ToCore", TO_CORE_TYPES), ("ToShell", TO_SHELL_TYPES)] {
            let mut tags = vec![];
            for branch in schema["$defs"][union]["oneOf"].as_array().unwrap() {
                let name = branch["$ref"].as_str().unwrap().rsplit('/').next().unwrap();
                let tag = schema["$defs"][name]["properties"]["type"]["const"]
                    .as_str()
                    .unwrap();
                tags.push(tag);
                // The enum knows the tag: a frame of that type fails on its fields, never on its variant.
                let empty = serde_json::json!({ "type": tag });
                let error = match union {
                    "ToCore" => serde_json::from_value::<ToCore>(empty).err(),
                    _ => serde_json::from_value::<ToShell>(empty).err(),
                };
                assert!(
                    error.is_none_or(|e| !e.to_string().contains("unknown variant")),
                    "{union} has no variant for {tag}"
                );
            }
            assert_eq!(tags, generated, "{union}");
        }
    }

    #[test]
    fn nullable_required_fields_stay_present() {
        let state = ToCore::DownloadState(DownloadState {
            download_id: "dl_01HZY0000000000000000000AB".into(),
            state: DownloadStateState::Queued,
            bytes_done: 0,
            bytes_total: 10,
            eta_s: None,
            error_code: None,
        });
        assert_eq!(
            line(&state),
            "{\"type\":\"control.download_state\",\"download_id\":\"dl_01HZY0000000000000000000AB\",\
             \"state\":\"queued\",\"bytes_done\":0,\"bytes_total\":10,\"eta_s\":null,\"error_code\":null}\n"
        );
        let file =
            r#"{"name":"a","url":"https://x","size_bytes":1,"sha256":"00","chunk_sha256":[]}"#;
        assert!(serde_json::from_str::<DownloadFilesItem>(file).is_err());
        let file = r#"{"name":"a","url":"https://x","size_bytes":1,"sha256":"00","chunk_sha256":[],"chunk_bytes":null}"#;
        assert_eq!(
            serde_json::from_str::<DownloadFilesItem>(file)
                .unwrap()
                .chunk_bytes,
            None
        );
    }

    #[test]
    fn secrets_never_show_in_debug_output() {
        let frames = [
            ToCore::Secret(Secret {
                name: SecretName::LaunchToken,
                profile_id: None,
                value: Redacted::new("launch-secret-value-0123456789abcdef"),
            }),
            ToCore::Keys(Keys {
                store: KeyStoreKind::OsKeychain,
                entries: vec![KeysEntriesItem {
                    r#ref: "jana.device-db".into(),
                    value: Redacted::new("launch-secret-value-0123456789abcdef"),
                }],
            }),
        ];
        for frame in frames {
            let shown = format!("{frame:?}");
            assert!(!shown.contains("launch-secret-value"), "{shown}");
            assert!(line(&frame).contains("launch-secret-value"));
        }
        let put = parse(
            r#"{"type":"control.key_put","ref":"jana.device-db","value":"c2VjcmV0LXZhbHVl"}"#,
        )
        .unwrap();
        assert!(!format!("{put:?}").contains("c2VjcmV0LXZhbHVl"));
    }

    #[test]
    fn round_trip_shapes() {
        assert_eq!(
            line(&ToCore::Hello(Hello {
                protocol: CONTROL_PROTOCOL,
                shell_version: None,
            })),
            "{\"type\":\"control.hello\",\"protocol\":{\"major\":1,\"minor\":4}}\n"
        );
        assert_eq!(
            line(&ToCore::Shutdown(Shutdown {
                grace_ms: Some(1000)
            })),
            "{\"type\":\"control.shutdown\",\"grace_ms\":1000}\n"
        );
        let config = line(&ToCore::Config(Config {
            data_dir: "/d".into(),
            content_root: "/c".into(),
            skills_root: "/s".into(),
            release: true,
            dev_origins: None,
            scripted: None,
            pilot_country_file: None,
        }));
        assert!(
            config.contains("\"type\":\"control.config\"")
                && !config.contains("dev_origins")
                && !config.contains("scripted")
                && !config.contains("pilot_country_file")
        );
        assert_eq!(
            parse(
                "{\"type\":\"control.ready\",\"protocol\":{\"major\":1,\"minor\":4},\"api_port\":4321,\"epoch\":\"0123456789abcdef\"}"
            ),
            Some(ToShell::Ready(Ready {
                protocol: CONTROL_PROTOCOL,
                api_port: 4321,
                epoch: "0123456789abcdef".into()
            }))
        );
        assert_eq!(
            parse(
                "{\"type\":\"control.error\",\"code\":\"protocol_mismatch\",\"expected_protocol\":{\"major\":2,\"minor\":0}}"
            ),
            Some(ToShell::Error(Error {
                code: "protocol_mismatch".into(),
                expected_protocol: Some(ProtocolVersion { major: 2, minor: 0 })
            }))
        );
        assert_eq!(parse("not json"), None);
    }
}
