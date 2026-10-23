//! The OS sandbox around the speech sidecar (VOC-23, SEC-06's mechanisms, SEC-09).
//!
//! The sidecar is native code from a signed speech pack that decodes audio and text; it needs loopback only (it
//! listens on `127.0.0.1` for the core and calls the core's adapter there) and reads only its own pack.
//!
//! - macOS: a Seatbelt profile, deny by default: reads of the pack, the system libraries and a per-launch scratch
//!   folder (metadata only on and above them); writes to the scratch folder alone; network to and from loopback
//!   only; no process creation; the Metal services the MLX and torch builds use on Apple silicon (TABLE VOC-03a).
//! - Linux: bubblewrap with the user, PID, IPC, UTS and cgroup namespaces unshared, the system folders and the pack
//!   bound read-only, a private `/tmp` and the scratch folder the only writable place. The network namespace is
//!   shared: the core must reach the sidecar's loopback port and the sidecar the core's adapter, which an empty
//!   namespace would cut. Network beyond loopback is refused inside the sidecar (`voice_sidecar.offline_process`).
//! - Windows: no wrapper yet. An AppContainer blocks loopback in both directions unless an administrator exempts it,
//!   so the Windows mechanism needs its own design (a brokered pipe instead of a loopback socket) and the Windows
//!   runner; the sidecar runs as the user, in the shell's job object, with the in-process refusals.
//!
//! A release build on macOS or Linux never starts the sidecar without its wrapper (`wrap` gives `None`).

use std::ffi::OsString;
use std::path::{Path, PathBuf};

const SANDBOX_EXEC: &str = "/usr/bin/sandbox-exec";
const BWRAP: [&str; 2] = ["/usr/bin/bwrap", "/bin/bwrap"]; // fixed paths: the sidecar's PATH is not consulted
/// Read beside the pack: system libraries, the dyld cache, time zone data.
const SEATBELT_SYSTEM: [&str; 6] = [
    "/System/Library",
    "/usr/lib",
    "/usr/share",
    "/private/var/db/dyld",
    "/System/Volumes/Preboot/Cryptexes",
    "/Library/Apple/System/Library",
];
const SEATBELT_DEVICES: [&str; 4] = [
    "/dev/null",
    "/dev/urandom",
    "/dev/random",
    "/private/etc/localtime",
];
/// The root's links into /private, which path resolution passes through.
const SEATBELT_ROOT_LINKS: [&str; 3] = ["/var", "/etc", "/tmp"];
const BWRAP_SYSTEM: [&str; 6] = [
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/etc/alternatives",
    "/etc/ld.so.cache",
];
/// GPU device nodes the CUDA build opens on the high class (TABLE VOC-03a), bound only where they exist.
const BWRAP_GPU: [&str; 5] = [
    "/dev/nvidiactl",
    "/dev/nvidia0",
    "/dev/nvidia-uvm",
    "/dev/nvidia-uvm-tools",
    "/dev/dri",
];

/// What confines one launch.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum Mechanism {
    Seatbelt,
    Bubblewrap,
    /// Windows (module docs), or a development build without the platform's wrapper.
    Unconfined,
}

/// The command that starts the sidecar inside its sandbox.
#[derive(Debug)]
pub struct Wrapped {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    pub mechanism: Mechanism,
}

/// The platform's wrapper around `program`, or `None` when a release build has no sandbox to put it in.
/// `interpreters` are extra programs the profile may run: the test bundles are shell scripts (always empty in a
/// build; a real sidecar is one frozen binary).
pub fn wrap(
    program: &Path,
    pack: &Path,
    scratch: &Path,
    release: bool,
    interpreters: &[&Path],
) -> Option<Wrapped> {
    let os = if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(windows) {
        "windows"
    } else {
        "linux"
    };
    wrap_for(os, program, pack, scratch, release, interpreters, |p| {
        p.is_file()
    })
}

fn wrap_for(
    os: &str,
    program: &Path,
    pack: &Path,
    scratch: &Path,
    release: bool,
    interpreters: &[&Path],
    exists: impl Fn(&Path) -> bool,
) -> Option<Wrapped> {
    let unconfined = || Wrapped {
        program: program.to_path_buf(),
        args: vec![],
        mechanism: Mechanism::Unconfined,
    };
    match os {
        "macos" if exists(Path::new(SANDBOX_EXEC)) => Some(Wrapped {
            program: SANDBOX_EXEC.into(),
            args: vec![
                "-p".into(),
                seatbelt_profile(program, pack, scratch, interpreters).into(),
                program.into(),
            ],
            mechanism: Mechanism::Seatbelt,
        }),
        "linux" => match BWRAP.iter().map(Path::new).find(|p| exists(p)) {
            Some(bwrap) => Some(Wrapped {
                program: bwrap.to_path_buf(),
                args: bubblewrap_args(program, pack, scratch),
                mechanism: Mechanism::Bubblewrap,
            }),
            None => (!release).then(unconfined),
        },
        "windows" => Some(unconfined()),
        _ => (!release).then(unconfined),
    }
}

fn sbpl(path: &Path) -> String {
    let text = path.to_string_lossy();
    format!("\"{}\"", text.replace('\\', "\\\\").replace('"', "\\\""))
}

/// Every folder above `paths` (path resolution stats each), plus the root's links into /private.
fn above(paths: &[PathBuf]) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = paths
        .iter()
        .flat_map(|p| p.ancestors().skip(1).map(Path::to_path_buf))
        .chain(SEATBELT_ROOT_LINKS.iter().map(PathBuf::from))
        .collect();
    out.sort();
    out.dedup();
    out
}

/// The sidecar's Seatbelt profile (module docs). Paths must be resolved (Seatbelt matches real paths).
pub fn seatbelt_profile(
    program: &Path,
    pack: &Path,
    scratch: &Path,
    interpreters: &[&Path],
) -> String {
    let subpaths: Vec<PathBuf> = [pack, scratch]
        .into_iter()
        .map(Path::to_path_buf)
        .chain(SEATBELT_SYSTEM.iter().map(PathBuf::from))
        .collect();
    let literals: Vec<PathBuf> = std::iter::once(program.to_path_buf())
        .chain(interpreters.iter().map(|p| p.to_path_buf()))
        .chain(SEATBELT_DEVICES.iter().map(PathBuf::from))
        .collect();
    let all: Vec<PathBuf> = subpaths.iter().chain(&literals).cloned().collect();
    let line = |kind: &str, p: &PathBuf| format!("  ({kind} {})", sbpl(p));
    let metadata: Vec<String> = above(&all).iter().map(|p| line("literal", p)).collect();
    let reads: Vec<String> = subpaths
        .iter()
        .map(|p| line("subpath", p))
        .chain(literals.iter().map(|p| line("literal", p)))
        .collect();
    let execs: Vec<String> = std::iter::once(program)
        .chain(interpreters.iter().copied())
        .map(|p| line("literal", &p.to_path_buf()))
        .collect();
    format!(
        r#"(version 1)
(deny default)
(deny process-fork)
(allow process-exec
{execs})
(allow signal (target self))
(allow sysctl-read)
(allow process-info* (target self))
(allow file-read-metadata
{metadata})
(allow file-read*
  (literal "/")
{reads})
(allow file-write*
  (subpath {scratch})
  (literal "/dev/null"))
(allow file-ioctl (literal "/dev/null"))
(allow system-socket)
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
(allow ipc-posix-shm-read* ipc-posix-shm-write-data (ipc-posix-name-prefix "apple.shm.notification_center"))
(allow mach-lookup
  (global-name "com.apple.system.opendirectoryd.libinfo")
  (global-name "com.apple.MTLCompilerService")
  (global-name "com.apple.gpumemd.source"))
(allow iokit-open
  (iokit-user-client-class "AGXDeviceUserClient")
  (iokit-user-client-class "AGXSharedUserClient")
  (iokit-user-client-class "IOSurfaceRootUserClient")
  (iokit-user-client-class "IOAccelerator"))
"#,
        execs = execs.join("\n"),
        metadata = metadata.join("\n"),
        reads = reads.join("\n"),
        scratch = sbpl(scratch),
    )
}

/// The sidecar's bubblewrap arguments (module docs), ending with `--` and the program.
pub fn bubblewrap_args(program: &Path, pack: &Path, scratch: &Path) -> Vec<OsString> {
    let mut args: Vec<OsString> = [
        "--unshare-user-try",
        "--unshare-ipc",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ]
    .map(OsString::from)
    .to_vec();
    let mut bind = |flag: &str, path: &Path| {
        args.extend([flag.into(), path.into(), path.into()]);
    };
    for system in BWRAP_SYSTEM {
        bind("--ro-bind-try", Path::new(system));
    }
    args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"].map(OsString::from));
    let mut bind = |flag: &str, path: &Path| {
        args.extend([flag.into(), path.into(), path.into()]);
    };
    bind("--ro-bind", pack); // after the private /tmp, so a pack folder under /tmp stays visible
    for device in BWRAP_GPU {
        bind("--dev-bind-try", Path::new(device));
    }
    bind("--bind", scratch);
    for (name, value) in [("HOME", scratch), ("TMPDIR", scratch)] {
        args.extend(["--setenv".into(), name.into(), value.into()]);
    }
    for (name, value) in [
        ("HF_HUB_OFFLINE", "1"),
        ("TRANSFORMERS_OFFLINE", "1"),
        ("LANG", "C.UTF-8"),
    ] {
        args.extend(["--setenv".into(), name.into(), value.into()]);
    }
    args.extend([
        "--chdir".into(),
        pack.into(),
        "--remount-ro".into(),
        "/".into(),
        "--".into(),
    ]);
    args.push(program.into());
    args
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paths() -> (PathBuf, PathBuf, PathBuf) {
        (
            PathBuf::from("/opt/packs/sp.en.1_0/sidecar/jana-voice"),
            PathBuf::from("/opt/packs/sp.en.1_0"),
            PathBuf::from("/private/var/folders/x/jana-voice-1"),
        )
    }

    #[test]
    fn test_voc23_sidecar_wrapped_per_platform() {
        let (program, pack, scratch) = paths();
        let all = |_: &Path| true;
        let none = |_: &Path| false;
        let mac = wrap_for("macos", &program, &pack, &scratch, true, &[], all).unwrap();
        assert_eq!(mac.mechanism, Mechanism::Seatbelt);
        assert_eq!(mac.program, PathBuf::from(SANDBOX_EXEC));
        assert_eq!(mac.args.last().unwrap(), program.as_os_str());
        let linux = wrap_for("linux", &program, &pack, &scratch, true, &[], all).unwrap();
        assert_eq!(linux.mechanism, Mechanism::Bubblewrap);
        assert_eq!(linux.args.last().unwrap(), program.as_os_str());
        // A release never starts the sidecar outside its sandbox; development may, to run without bubblewrap.
        assert!(wrap_for("linux", &program, &pack, &scratch, true, &[], none).is_none());
        assert!(wrap_for("macos", &program, &pack, &scratch, true, &[], none).is_none());
        let dev = wrap_for("linux", &program, &pack, &scratch, false, &[], none).unwrap();
        assert_eq!(
            (dev.mechanism, dev.program),
            (Mechanism::Unconfined, program.clone())
        );
        let windows = wrap_for("windows", &program, &pack, &scratch, true, &[], all).unwrap();
        assert_eq!(
            windows.mechanism,
            Mechanism::Unconfined,
            "Windows: see the module docs"
        );
    }

    #[test]
    fn test_voc23_seatbelt_profile_loopback_only() {
        let (program, pack, scratch) = paths();
        let profile = seatbelt_profile(&program, &pack, &scratch, &[]);
        assert!(profile.contains("(deny default)") && profile.contains("(deny process-fork)"));
        assert!(
            !profile.contains("(allow network*") && !profile.contains("(allow network-outbound)\n")
        );
        for rule in [
            "network-bind (local ip",
            "network-inbound (local ip",
            "network-outbound (remote ip",
        ] {
            assert!(
                profile.contains(&format!("(allow {rule} \"localhost:*\"))")),
                "{rule}"
            );
        }
        assert!(
            !profile.contains("(allow file-read-metadata)"),
            "metadata is scoped"
        );
        assert!(
            profile.contains("  (literal \"/opt/packs\")"),
            "the folders above the pack"
        );
        let writes = profile
            .split("(allow file-write*")
            .nth(1)
            .unwrap()
            .split("))")
            .next()
            .unwrap();
        assert!(
            writes.contains(&format!("(subpath {})", sbpl(&scratch)))
                && !writes.contains("/opt/packs"),
            "the pack is read-only"
        );
        let execs = profile
            .split("(allow process-exec")
            .nth(1)
            .unwrap()
            .split(')')
            .next()
            .unwrap();
        assert!(
            execs.contains("jana-voice") && !execs.contains("/bin/sh"),
            "only the sidecar runs"
        );
        let quoted = seatbelt_profile(Path::new("/a\"b"), &pack, &scratch, &[]);
        assert!(
            quoted.contains("\"/a\\\"b\""),
            "paths are quoted for the profile language"
        );
    }

    #[test]
    fn test_voc23_bubblewrap_pack_read_only() {
        let (program, pack, scratch) = paths();
        let args: Vec<String> = bubblewrap_args(&program, &pack, &scratch)
            .iter()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        let at = |flag: &str, path: &Path| {
            args.windows(3).any(|w| {
                w[0] == flag && w[1] == path.to_string_lossy() && w[2] == path.to_string_lossy()
            })
        };
        assert!(at("--ro-bind", &pack) && at("--bind", &scratch) && !at("--bind", &pack));
        assert!(args.contains(&"--unshare-pid".into()) && args.contains(&"--clearenv".into()));
        let tail = &args[args.len() - 2..];
        assert_eq!(
            tail,
            ["--".to_string(), program.to_string_lossy().into_owned()]
        );
        if let Ok(home) = std::env::var("HOME") {
            assert!(!args.contains(&home), "the user's home is never bound");
        }
    }
}
