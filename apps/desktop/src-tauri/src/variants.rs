//! The llama.cpp builds the bundle carries and the one the shell starts (PLT-04, TABLE PLT-04a).
//!
//! Every build comes from one pinned llama.cpp commit and sits at `resources/runtime/<variant>/llama-server[.exe]`.
//! At start the shell reads the CPU's instruction sets and asks the Vulkan build which devices it sees, then orders
//! the builds this machine may run, best first: on Windows and Linux `vulkan` (a device with enough dedicated or
//! shared memory), `cpu-avx2` (AVX2 and FMA), `cpu-baseline` (SSE4.2); on Apple silicon `metal`, then `cpu-arm64`.
//! A build this machine cannot run is left out with why, so a CPU without AVX2 never starts the AVX2 build and never
//! dies of an illegal instruction. When the chosen build fails its touch generation the runtime supervisor moves to
//! the next one down and records why; past the last there is no runtime, and the core reports the content-only class.

use crate::generated::keys;
use crate::runtime::{Build, Builds, RuntimeCommand};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

/// A build in TABLE PLT-04a. `Cuda` is the school server's (PLT-25); the desktop bundle never carries it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Variant {
    Vulkan,
    CpuAvx2,
    CpuBaseline,
    Metal,
    CpuArm64,
    Cuda,
}

impl Variant {
    pub const ALL: [Variant; 6] = [
        Variant::Vulkan,
        Variant::CpuAvx2,
        Variant::CpuBaseline,
        Variant::Metal,
        Variant::CpuArm64,
        Variant::Cuda,
    ];

    /// The build's folder name and the name the health panel shows.
    pub fn name(self) -> &'static str {
        match self {
            Variant::Vulkan => "vulkan",
            Variant::CpuAvx2 => "cpu-avx2",
            Variant::CpuBaseline => "cpu-baseline",
            Variant::Metal => "metal",
            Variant::CpuArm64 => "cpu-arm64",
            Variant::Cuda => "cuda",
        }
    }

    pub fn from_name(name: &str) -> Option<Variant> {
        Variant::ALL.into_iter().find(|v| v.name() == name)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Os {
    Windows,
    Linux,
    MacOs,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Arch {
    X86_64,
    Arm64,
    Other,
}

/// What the choice reads of this machine's CPU.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cpu {
    pub os: Os,
    pub arch: Arch,
    pub sse42: bool,
    pub avx2: bool,
    pub fma: bool,
}

/// This machine's CPU, read with the CPU's own feature flags.
pub fn this_cpu() -> Cpu {
    let os = if cfg!(target_os = "macos") {
        Os::MacOs
    } else if cfg!(windows) {
        Os::Windows
    } else {
        Os::Linux
    };
    #[cfg(target_arch = "x86_64")]
    {
        Cpu {
            os,
            arch: Arch::X86_64,
            sse42: std::arch::is_x86_feature_detected!("sse4.2"),
            avx2: std::arch::is_x86_feature_detected!("avx2"),
            fma: std::arch::is_x86_feature_detected!("fma"),
        }
    }
    #[cfg(target_arch = "aarch64")]
    {
        Cpu {
            os,
            arch: Arch::Arm64,
            sse42: false,
            avx2: false,
            fma: false,
        }
    }
    #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
    {
        Cpu {
            os,
            arch: Arch::Other,
            sse42: false,
            avx2: false,
            fma: false,
        }
    }
}

/// One device line of `llama-server --list-devices`: `  Vulkan0: <name> (<total> MiB, <free> MiB free)`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Device {
    pub id: String,
    pub name: String,
    pub total_mib: u64,
}

pub fn parse_devices(text: &str) -> Vec<Device> {
    text.lines()
        .filter_map(|line| {
            let (id, rest) = line.trim().split_once(": ")?;
            let open = rest.rfind(" (")?;
            let total = rest[open + 2..].split_whitespace().next()?.parse().ok()?;
            Some(Device {
                id: id.to_string(),
                name: rest[..open].to_string(),
                total_mib: total,
            })
        })
        .collect()
}

/// Integrated graphics share the system's memory; a discrete card has its own.
fn integrated(name: &str) -> bool {
    let name = name.to_ascii_lowercase();
    [
        "intel",
        "radeon(tm) graphics",
        "radeon graphics",
        "vega",
        "adreno",
        "mali",
    ]
    .iter()
    .any(|marker| name.contains(marker))
        && !name.contains("arc a")
}

/// TABLE PLT-04a: a Vulkan device with at least the dedicated minimum of its own memory, or the shared minimum when
/// it is integrated graphics. The Vulkan build lists only devices its loader accepts (Vulkan 1.2 or later).
pub fn device_qualifies(device: &Device, min_dedicated_gb: f64, min_shared_gb: f64) -> bool {
    let gb = device.total_mib as f64 / 1024.0;
    device.id.starts_with("Vulkan")
        && if integrated(&device.name) {
            gb >= min_shared_gb
        } else {
            gb >= min_dedicated_gb
        }
}

/// What the Vulkan build said about this machine's devices.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VulkanProbe {
    /// No Vulkan build for this platform, or none bundled.
    NotBundled,
    /// The probe crashed, hung or could not start: the driver is not usable.
    Failed(String),
    Devices(Vec<Device>),
}

/// The builds this machine may run, best first, and those left out with why (TABLE PLT-04a).
pub fn ladder(cpu: Cpu, vulkan: &VulkanProbe) -> (Vec<Variant>, Vec<(Variant, String)>) {
    let mut chosen = Vec::new();
    let mut skipped = Vec::new();
    let (dedicated, shared) = (
        keys::RUNTIME_VULKAN_MIN_DEDICATED_GB,
        keys::RUNTIME_VULKAN_MIN_SHARED_GB,
    );
    if cpu.os == Os::MacOs && cpu.arch == Arch::Arm64 {
        return (vec![Variant::Metal, Variant::CpuArm64], skipped);
    }
    if cpu.os != Os::MacOs {
        match vulkan {
            VulkanProbe::NotBundled => {}
            VulkanProbe::Failed(why) => skipped.push((Variant::Vulkan, why.clone())),
            VulkanProbe::Devices(devices) => {
                if devices
                    .iter()
                    .any(|d| device_qualifies(d, dedicated, shared))
                {
                    chosen.push(Variant::Vulkan);
                } else {
                    skipped.push((
                        Variant::Vulkan,
                        format!(
                            "no Vulkan device with {dedicated} GB of its own memory or {shared} GB shared"
                        ),
                    ));
                }
            }
        }
    }
    match cpu.arch {
        Arch::X86_64 => {
            if cpu.avx2 && cpu.fma {
                chosen.push(Variant::CpuAvx2);
            } else {
                skipped.push((Variant::CpuAvx2, "the CPU has no AVX2 and FMA".into()));
            }
            if cpu.sse42 {
                chosen.push(Variant::CpuBaseline);
            } else {
                skipped.push((Variant::CpuBaseline, "the CPU has no SSE4.2".into()));
            }
        }
        Arch::Arm64 => chosen.push(Variant::CpuArm64),
        Arch::Other => skipped.push((Variant::CpuBaseline, "not a 64-bit CPU".into())),
    }
    (chosen, skipped)
}

/// The bundled program of a build: `<resources>/runtime/<variant>/llama-server[.exe]`.
pub fn program(resources: &Path, variant: Variant) -> PathBuf {
    let exe = if cfg!(windows) {
        "llama-server.exe"
    } else {
        "llama-server"
    };
    resources.join("runtime").join(variant.name()).join(exe)
}

/// The bundled builds this machine may run, best first, each started with `prefix_args` before llama-server's own
/// arguments; a build the table allows but the bundle lacks is left out as such. The Vulkan build is asked for its
/// devices only where a Vulkan build applies.
pub fn select(resources: &Path, cpu: Cpu, prefix_args: &[String]) -> Builds {
    let vulkan_program = program(resources, Variant::Vulkan);
    let vulkan = if cpu.os != Os::MacOs && vulkan_program.is_file() {
        let timeout = Duration::from_secs_f64(keys::RUNTIME_VARIANT_PROBE_S);
        probe_devices(&vulkan_program, prefix_args, timeout)
    } else {
        VulkanProbe::NotBundled
    };
    let (order, mut skipped) = ladder(cpu, &vulkan);
    let mut builds = Vec::new();
    for variant in order {
        let path = program(resources, variant);
        if path.is_file() {
            builds.push(Build {
                variant: Some(variant),
                command: RuntimeCommand {
                    program: path,
                    prefix_args: prefix_args.to_vec(),
                },
            });
        } else {
            skipped.push((variant, "not in this bundle".into()));
        }
    }
    Builds {
        ladder: builds,
        skipped,
    }
}

/// Ask a build which devices it sees (`--list-devices`), within `timeout`; a crash or a hang is a failed probe.
pub fn probe_devices(program: &Path, prefix_args: &[String], timeout: Duration) -> VulkanProbe {
    let spawned = Command::new(program)
        .args(prefix_args)
        .arg("--list-devices")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn();
    let mut child = match spawned {
        Ok(child) => child,
        Err(_) => return VulkanProbe::Failed("the Vulkan build could not be started".into()),
    };
    let started = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if started.elapsed() < timeout => thread::sleep(Duration::from_millis(20)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return VulkanProbe::Failed("the Vulkan device probe did not finish".into());
            }
        }
    };
    let mut out = String::new();
    if let Some(mut stdout) = child.stdout.take() {
        let _ = stdout.read_to_string(&mut out);
    }
    if !status.success() {
        return VulkanProbe::Failed(format!(
            "the Vulkan device probe failed ({})",
            exit_reason(&status)
        ));
    }
    VulkanProbe::Devices(parse_devices(&out))
}

/// How a process ended, in words for the health panel: an illegal instruction and a crash are named.
pub fn exit_reason(status: &std::process::ExitStatus) -> String {
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        if let Some(signal) = status.signal() {
            return match signal {
                4 => "illegal instruction".into(),
                11 => "crashed (segmentation fault)".into(),
                6 => "crashed (aborted)".into(),
                9 => "killed".into(),
                other => format!("ended by signal {other}"),
            };
        }
    }
    match status.code() {
        Some(code) => format!("exit code {code}"),
        None => "ended".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cpu(avx2: bool) -> Cpu {
        Cpu {
            os: Os::Windows,
            arch: Arch::X86_64,
            sse42: true,
            avx2,
            fma: avx2,
        }
    }

    #[test]
    fn device_lines_parse() {
        let text = "Available devices:\n  Vulkan0: NVIDIA GeForce RTX 3050 Laptop GPU (4096 MiB, 3900 MiB free)\n  \
                    Vulkan1: Intel(R) UHD Graphics 620 (3072 MiB, 3000 MiB free)\n";
        let devices = parse_devices(text);
        assert_eq!(devices.len(), 2);
        assert_eq!(devices[0].name, "NVIDIA GeForce RTX 3050 Laptop GPU");
        assert!(device_qualifies(&devices[0], 2.0, 4.0));
        assert!(!device_qualifies(&devices[1], 2.0, 4.0)); // integrated: needs 4 GB shared
    }

    #[test]
    fn apple_silicon_prefers_metal() {
        let mac = Cpu {
            os: Os::MacOs,
            arch: Arch::Arm64,
            sse42: false,
            avx2: false,
            fma: false,
        };
        assert_eq!(
            ladder(mac, &VulkanProbe::NotBundled).0,
            [Variant::Metal, Variant::CpuArm64]
        );
    }

    #[test]
    fn a_failed_vulkan_probe_is_recorded() {
        let (chosen, skipped) = ladder(cpu(true), &VulkanProbe::Failed("crashed".into()));
        assert_eq!(chosen, [Variant::CpuAvx2, Variant::CpuBaseline]);
        assert_eq!(skipped, [(Variant::Vulkan, "crashed".to_string())]);
    }
}
