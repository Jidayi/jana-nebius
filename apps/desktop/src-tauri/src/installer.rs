//! The installer's checks before it copies anything (PLT-01, PLT-06, PLT-29), shared by the Windows installers (the
//! NSIS and MSI hooks run the `jana-precheck` binary from the installer's temporary folder) and by the first start of a
//! drag-installed macOS app or AppImage.
//!
//! - **Operating system** (TABLE PLT-01a): Windows 10 22H2 (build 19045) or Windows 11 on x64; macOS 13 or later on
//!   Apple silicon; Ubuntu 22.04 or later and Debian 12 or later on x64 (best effort: other distributions are not
//!   refused). An older system, or a Mac with an Intel processor, stops the installer with a message that names what
//!   it needs.
//! - **Disk** (PLT-06): the app plus the selected packs must fit; otherwise the installer stops before copying and says
//!   how much is needed and how much is free.
//! - **Minimum laptop** (PLT-29): below the minimum (memory, a 64-bit processor, free disk) the app is still installed,
//!   with a notice that the tutor model will not run offline here; lessons and practice work.
//!
//! Every message is a key of the installers' catalogue, `installer/strings.json` (LOC-01), embedded here: the checks
//! decide a [`Message`] (a key and its figures) and [`Message::text`] words it in the installer's language, falling
//! back to English for a locale the catalogue does not have yet.

use crate::generated::keys;
use serde_json::{Map, Value};
use std::sync::OnceLock;

const GB: f64 = 1024.0 * 1024.0 * 1024.0;
/// Windows 10 22H2 is build 19045; every Windows 11 build is above it (TABLE PLT-01a).
const WINDOWS_MIN_BUILD: u32 = 19045;
const MACOS_MIN_MAJOR: u32 = 13;
const UBUNTU_MIN: (u32, u32) = (22, 4);
const DEBIAN_MIN: (u32, u32) = (12, 0);

/// The installers' catalogue (LOC-01), shared with the NSIS hooks.
const CATALOGUE: &str = include_str!("../installer/strings.json");
const FALLBACK_LOCALE: &str = "en";
/// Locales whose decimal separator is a comma.
const DECIMAL_COMMA: &[&str] = &["fr", "pt"];
/// The Windows primary language id (the low ten bits of a language id such as NSIS's `$LANGUAGE`) of each locale.
const PRIMARY_LANGUAGE_IDS: &[(u32, &str)] =
    &[(0x09, "en"), (0x0C, "fr"), (0x16, "pt"), (0x01, "ar")];

/// Every key the precheck shows.
pub const MESSAGE_KEYS: &[&str] = &[
    "janaPrecheckWindowsTooOld",
    "janaPrecheckMacIntel",
    "janaPrecheckMacTooOld",
    "janaPrecheckLinuxArch",
    "janaPrecheckLinuxTooOld",
    "janaPrecheckOtherSystem",
    "janaPrecheckDiskFull",
    "janaPrecheckBelowMinimum",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Family {
    Windows,
    MacOs,
    Linux,
    Other,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Arch {
    X86_64,
    Arm64,
    Other,
}

/// What the check reads of the machine.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OsInfo {
    pub family: Family,
    pub arch: Arch,
    /// `os_version` as the OS reports it: "10 (19045)" on Windows, "13.6.1" on macOS, "22.04" on Linux.
    pub version: String,
    /// The distribution id on Linux ("ubuntu", "debian"), empty elsewhere.
    pub distribution: String,
}

/// A message the installer shows: a catalogue key and the sizes (in GB) its placeholders name.
#[derive(Debug, Clone, PartialEq)]
pub struct Message {
    pub key: &'static str,
    pub gigabytes: Vec<(&'static str, f64)>,
}

impl Message {
    fn plain(key: &'static str) -> Message {
        Message {
            key,
            gigabytes: vec![],
        }
    }

    /// The message in `locale`'s words (English where the locale lacks the key), placeholders filled.
    pub fn text(&self, locale: &str) -> String {
        let (template, used) = match words(locale, self.key) {
            Some(text) => (text, locale),
            None => (
                words(FALLBACK_LOCALE, self.key).unwrap_or(self.key),
                FALLBACK_LOCALE,
            ),
        };
        let comma = DECIMAL_COMMA.contains(&used);
        self.gigabytes
            .iter()
            .fold(template.to_string(), |text, (name, value)| {
                let mut figure = format!("{value:.1}");
                if comma {
                    figure = figure.replace('.', ",");
                }
                text.replace(&format!("{{{name}}}"), &figure)
            })
    }
}

fn catalogue() -> &'static Map<String, Value> {
    static PARSED: OnceLock<Map<String, Value>> = OnceLock::new();
    PARSED.get_or_init(|| serde_json::from_str(CATALOGUE).unwrap_or_default())
}

fn words(locale: &str, key: &str) -> Option<&'static str> {
    catalogue().get(locale)?.get(key)?.as_str()
}

/// The catalogue locale for the installer's language: a Windows language id (NSIS `$LANGUAGE`, MSI
/// `UserLanguageID`) or a locale name such as `fr` or `fr_FR.UTF-8`; English when it names none the catalogue has.
pub fn locale_for(language: Option<&str>) -> &'static str {
    let Some(language) = language.map(str::trim).filter(|l| !l.is_empty()) else {
        return FALLBACK_LOCALE;
    };
    let found = if let Ok(id) = language.parse::<u32>() {
        PRIMARY_LANGUAGE_IDS
            .iter()
            .find(|(primary, _)| *primary == id & 0x3FF)
            .map(|(_, locale)| *locale)
    } else {
        let code = language
            .split(['_', '-', '.'])
            .next()
            .unwrap_or("")
            .to_ascii_lowercase();
        PRIMARY_LANGUAGE_IDS
            .iter()
            .map(|(_, locale)| *locale)
            .find(|locale| *locale == code)
    };
    found
        .filter(|locale| catalogue().contains_key(*locale))
        .unwrap_or(FALLBACK_LOCALE)
}

fn numbers(text: &str) -> Vec<u32> {
    text.split(|c: char| !c.is_ascii_digit())
        .filter(|s| !s.is_empty())
        .filter_map(|s| s.parse().ok())
        .collect()
}

/// The message that stops the installer on an unsupported system, or `None` when the system is supported.
pub fn unsupported_os_message(os: &OsInfo) -> Option<Message> {
    let parts = numbers(&os.version);
    let key = match os.family {
        Family::Windows => {
            let build = parts.get(1).copied().unwrap_or(0);
            let major = parts.first().copied().unwrap_or(0);
            (os.arch != Arch::X86_64 || major < 10 || build < WINDOWS_MIN_BUILD)
                .then_some("janaPrecheckWindowsTooOld")
        }
        Family::MacOs => {
            if os.arch != Arch::Arm64 {
                Some("janaPrecheckMacIntel")
            } else {
                (parts.first().copied().unwrap_or(0) < MACOS_MIN_MAJOR)
                    .then_some("janaPrecheckMacTooOld")
            }
        }
        Family::Linux => {
            if os.arch != Arch::X86_64 {
                Some("janaPrecheckLinuxArch")
            } else {
                let version = (
                    parts.first().copied().unwrap_or(0),
                    parts.get(1).copied().unwrap_or(0),
                );
                let old = match os.distribution.as_str() {
                    "ubuntu" => version < UBUNTU_MIN,
                    "debian" => version < DEBIAN_MIN,
                    _ => false, // best effort: other distributions are not refused
                };
                old.then_some("janaPrecheckLinuxTooOld")
            }
        }
        Family::Other => Some("janaPrecheckOtherSystem"),
    };
    key.map(Message::plain)
}

/// PLT-06: stop before copying when the app and the selected packs do not fit, naming both amounts.
pub fn disk_precheck(needed_bytes: u64, free_bytes: u64) -> Result<(), Message> {
    if free_bytes >= needed_bytes {
        return Ok(());
    }
    Err(Message {
        key: "janaPrecheckDiskFull",
        gigabytes: vec![
            ("needed", needed_bytes as f64 / GB),
            ("free", free_bytes as f64 / GB),
        ],
    })
}

/// PLT-29: below the minimum laptop the app still installs; this notice says the tutor model will not run offline.
pub fn minimum_laptop_notice(ram_bytes: u64, free_bytes: u64, os: &OsInfo) -> Option<Message> {
    let low_ram = (ram_bytes as f64) < keys::MINIMUM_RAM_GB * GB;
    let low_disk = (free_bytes as f64) < keys::MINIMUM_FREE_DISK_GB * GB;
    let not_64 = os.arch == Arch::Other;
    (low_ram || low_disk || not_64).then(|| Message::plain("janaPrecheckBelowMinimum"))
}

/// What the installer does next.
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    /// Install; an optional notice to show (PLT-29).
    Proceed(Option<Message>),
    /// Stop before copying, with the message to show.
    Stop(Message),
}

impl Outcome {
    /// The precheck binary's exit code: 0 proceed, 2 stop.
    pub fn exit_code(&self) -> i32 {
        match self {
            Outcome::Proceed(_) => 0,
            Outcome::Stop(_) => 2,
        }
    }

    /// The message to show, in `locale`'s words, if any.
    pub fn text(&self, locale: &str) -> Option<String> {
        match self {
            Outcome::Stop(message) | Outcome::Proceed(Some(message)) => Some(message.text(locale)),
            Outcome::Proceed(None) => None,
        }
    }
}

/// Every check in order: the system, then the disk, then the minimum-laptop notice.
pub fn precheck(os: &OsInfo, needed_bytes: u64, free_bytes: u64, ram_bytes: u64) -> Outcome {
    if let Some(message) = unsupported_os_message(os) {
        return Outcome::Stop(message);
    }
    if let Err(message) = disk_precheck(needed_bytes, free_bytes) {
        return Outcome::Stop(message);
    }
    Outcome::Proceed(minimum_laptop_notice(ram_bytes, free_bytes, os))
}

/// `text` as UTF-16LE without a byte-order mark, the form NSIS's `FileReadUTF16LE` reads whatever the system's code
/// page (the precheck's stdout is UTF-8, which an installer would show garbled for a non-English locale).
pub fn utf16le(text: &str) -> Vec<u8> {
    text.encode_utf16().flat_map(u16::to_le_bytes).collect()
}

/// This machine, read without elevated rights.
pub fn this_os() -> OsInfo {
    let family = match std::env::consts::OS {
        "windows" => Family::Windows,
        "macos" => Family::MacOs,
        "linux" => Family::Linux,
        _ => Family::Other,
    };
    let arch = match std::env::consts::ARCH {
        "x86_64" => Arch::X86_64,
        "aarch64" => Arch::Arm64,
        _ => Arch::Other,
    };
    OsInfo {
        family,
        arch,
        version: sysinfo::System::os_version().unwrap_or_default(),
        distribution: if family == Family::Linux {
            sysinfo::System::distribution_id()
        } else {
            String::new()
        },
    }
}

/// Installed memory in bytes.
pub fn this_ram_bytes() -> u64 {
    let mut system = sysinfo::System::new();
    system.refresh_memory();
    system.total_memory()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn os(family: Family, arch: Arch, version: &str, distribution: &str) -> OsInfo {
        OsInfo {
            family,
            arch,
            version: version.into(),
            distribution: distribution.into(),
        }
    }

    fn english(message: Option<Message>) -> String {
        message.expect("a message").text("en")
    }

    /// PLT-01: on an unsupported OS version the installer stops with a message naming the version it needs; every
    /// `must` row of TABLE PLT-01a passes.
    #[test]
    fn plt01_unsupported_os_message() {
        let old_windows = os(Family::Windows, Arch::X86_64, "10 (19044)", "");
        let message = english(unsupported_os_message(&old_windows));
        assert!(message.contains("too old") && message.contains("Windows 10 version 22H2"));
        let outcome = precheck(&old_windows, 1, u64::MAX, u64::MAX);
        assert_eq!(outcome.exit_code(), 2);

        let old_mac = os(Family::MacOs, Arch::Arm64, "12.7.4", "");
        assert!(english(unsupported_os_message(&old_mac)).contains("macOS 13"));
        let intel_mac = os(Family::MacOs, Arch::X86_64, "14.4", "");
        assert!(english(unsupported_os_message(&intel_mac)).contains("Apple silicon"));
        assert!(
            unsupported_os_message(&os(Family::Windows, Arch::Arm64, "11 (22631)", "")).is_some()
        );
        assert!(
            unsupported_os_message(&os(Family::Linux, Arch::X86_64, "20.04", "ubuntu")).is_some()
        );

        for supported in [
            os(Family::Windows, Arch::X86_64, "10 (19045)", ""),
            os(Family::Windows, Arch::X86_64, "11 (22631)", ""),
            os(Family::MacOs, Arch::Arm64, "13.0", ""),
            os(Family::MacOs, Arch::Arm64, "15.1.1", ""),
            os(Family::Linux, Arch::X86_64, "22.04", "ubuntu"),
            os(Family::Linux, Arch::X86_64, "12", "debian"),
            os(Family::Linux, Arch::X86_64, "40", "fedora"),
        ] {
            assert_eq!(unsupported_os_message(&supported), None, "{supported:?}");
        }
    }

    /// PLT-06: with too little disk the installer stops before copying, saying how much is needed and how much is
    /// free; with enough it proceeds.
    #[test]
    fn plt06_disk_space_precheck() {
        let windows = os(Family::Windows, Arch::X86_64, "10 (19045)", "");
        let needed = (3.4 * GB) as u64;
        let free = (1.2 * GB) as u64;
        let outcome = precheck(&windows, needed, free, (16.0 * GB) as u64);
        assert_eq!(outcome.exit_code(), 2);
        let message = outcome.text("en").unwrap();
        assert!(
            message.contains("3.4 GB") && message.contains("1.2 GB free"),
            "{message}"
        );
        assert!(disk_precheck(needed, needed).is_ok());
        assert!(matches!(
            precheck(&windows, needed, (40.0 * GB) as u64, (16.0 * GB) as u64),
            Outcome::Proceed(None)
        ));
    }

    /// PLT-29 through PLT-06: a machine below the minimum laptop is installed with the notice, never refused.
    #[test]
    fn below_minimum_installs_with_notice() {
        let windows = os(Family::Windows, Arch::X86_64, "10 (19045)", "");
        let outcome = precheck(
            &windows,
            (1.0 * GB) as u64,
            (40.0 * GB) as u64,
            (4.0 * GB) as u64,
        );
        assert_eq!(outcome.exit_code(), 0);
        assert!(
            outcome
                .text("en")
                .unwrap()
                .contains("Lessons and practice will work")
        );
    }

    /// LOC-01: every message the precheck shows is a key of the installers' catalogue, every locale there has it,
    /// and each is shown in the installer's language with its placeholders filled; an unknown language reads English.
    #[test]
    fn precheck_messages_are_catalogue_keys() {
        let catalogue = catalogue();
        assert!(catalogue.contains_key("en"), "the catalogue parses");
        for (locale, entries) in catalogue.iter().filter(|(l, _)| !l.starts_with('_')) {
            for key in MESSAGE_KEYS {
                let text = entries.get(*key).and_then(Value::as_str);
                assert!(text.is_some_and(|t| !t.is_empty()), "{locale} lacks {key}");
            }
        }
        let every = [
            Message::plain("janaPrecheckWindowsTooOld"),
            Message::plain("janaPrecheckOtherSystem"),
            disk_precheck(2 << 30, 1 << 30).unwrap_err(),
        ];
        for message in &every {
            let text = message.text("en");
            assert!(!text.contains('{') && text != message.key, "{text}");
        }
        // Another locale's words are used when the catalogue has them; a locale it lacks, or a missing key, reads
        // English rather than a key.
        let disk = disk_precheck((3.4 * GB) as u64, (1.2 * GB) as u64).unwrap_err();
        assert_eq!(disk.text("xx"), disk.text("en"));
        assert!(disk.text("fr").contains("3"), "{}", disk.text("fr"));
        assert_eq!(locale_for(None), "en");
        assert_eq!(locale_for(Some("1033")), "en");
        assert_eq!(locale_for(Some("9999999")), "en");
        assert_eq!(locale_for(Some("en_GB.UTF-8")), "en");
        for (id, code) in [
            ("1036", "fr"),
            ("2060", "fr"),
            ("2070", "pt"),
            ("1025", "ar"),
        ] {
            let expected = if catalogue.contains_key(code) {
                code
            } else {
                "en"
            };
            assert_eq!(locale_for(Some(id)), expected, "{id}");
            assert_eq!(locale_for(Some(code)), expected, "{code}");
        }
    }

    #[test]
    fn messages_reach_nsis_as_utf16() {
        assert_eq!(utf16le("Aé"), [0x41, 0x00, 0xE9, 0x00]);
    }

    #[test]
    fn this_machine_reads() {
        let here = this_os();
        assert_ne!(here.family, Family::Other);
        assert!(this_ram_bytes() > 0);
    }
}
