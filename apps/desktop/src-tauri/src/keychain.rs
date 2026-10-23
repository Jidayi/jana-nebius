//! The shell's key store for the core's device secrets (SEC-17, D97, G81).
//!
//! The shell keeps the secrets in the OS keychain (macOS Keychain, Windows Credential Manager, the Linux Secret
//! Service) and hands every one it holds to the core with `control.keys` before `control.config`; the core asks it to
//! store or delete one with `control.key_put` and `control.key_delete`, and the shell answers each with
//! `control.key_result`, in order. Where no keychain service exists, the secrets live in the SEC-17 file fallback: one
//! file per reference, mode 0600, in a 0700 folder outside the app data folder, in the layout the core's
//! `FileKeyStore` reads (so its uninstall command can clear it, PLT-24).
//!
//! A value never appears in a log, a crash record, a panic message or `Debug` output; references may.

use crate::control::{
    KeyDelete, KeyPut, KeyResult, KeyResultOp, KeyStoreKind, Keys, KeysEntriesItem, Redacted,
    ToCore, ToShell,
};
use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

/// The keychain item listing the references the shell holds (keychains cannot list their items portably). It is
/// not a reference itself: references always start with `jana.`.
const INDEX_ACCOUNT: &str = "index";
/// The reference prefix and the bounds of what follows it (`$defs/KeyRef`).
const REF_PREFIX: &str = "jana.";
const REF_TAIL: std::ops::RangeInclusive<usize> = 2..=76;
/// The longest value the contract carries (`$defs/KeyValue`).
const VALUE_MAX: usize = 4096;
/// The most entries one `control.keys` carries (`$defs/Keys`).
const ENTRIES_MAX: usize = 64;
/// Windows Credential Manager items are written with local persistence (`CRED_PERSIST_LOCAL_MACHINE`): never the
/// store's default, enterprise persistence, which copies an item to every machine a roaming profile signs in to
/// (SEC-17: DPAPI for the current user, on this device). The other keychains take no modifiers.
const PERSISTENCE: Option<(&str, &str)> = if cfg!(windows) {
    Some(("persistence", "Local"))
} else {
    None
};

/// Where the secrets are kept.
pub struct KeyStore {
    backend: Backend,
}

enum Backend {
    Keychain(Keychain),
    Files(PathBuf),
    /// Neither the keychain nor the fallback folder could be opened: nothing is held and every request fails, so the
    /// core keeps its secrets for the run and shows the keychain line degraded.
    Unavailable,
    /// Tests only: a release build never selects it (SEC-17).
    #[cfg(test)]
    Memory(Mutex<std::collections::BTreeMap<String, String>>),
}

struct Keychain {
    store: Arc<keyring_core::CredentialStore>,
    service: String,
    /// Serialises index updates.
    index: Mutex<()>,
}

impl fmt::Debug for KeyStore {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.backend {
            Backend::Keychain(keychain) => write!(f, "KeyStore(os_keychain, {})", keychain.service),
            Backend::Files(dir) => write!(f, "KeyStore(user_file, {})", dir.display()),
            Backend::Unavailable => f.write_str("KeyStore(unavailable)"),
            #[cfg(test)]
            Backend::Memory(_) => f.write_str("KeyStore(memory)"),
        }
    }
}

/// Whether `name` is a key reference (`$defs/KeyRef`); file names are made from references, so nothing else passes.
pub fn is_ref(name: &str) -> bool {
    name.strip_prefix(REF_PREFIX).is_some_and(|tail| {
        REF_TAIL.contains(&tail.len())
            && tail
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"._-".contains(&b))
    })
}

fn is_value(value: &str) -> bool {
    (1..=VALUE_MAX).contains(&value.len()) && decode(value).is_some()
}

impl KeyStore {
    /// The OS keychain under `service` (the app's bundle identifier) where its service is available, else the file
    /// fallback in `fallback` (refused inside `data_dir`), else a store that holds nothing.
    pub fn open(service: &str, fallback: PathBuf, data_dir: &Path) -> KeyStore {
        KeyStore::keychain(service)
            .or_else(|| KeyStore::files(fallback, data_dir).ok())
            .unwrap_or(KeyStore {
                backend: Backend::Unavailable,
            })
    }

    /// The OS keychain, or `None` where its service cannot be reached (for example a Linux desktop without the
    /// Secret Service).
    pub fn keychain(service: &str) -> Option<KeyStore> {
        let store = os_store()?;
        let keychain = Keychain {
            store,
            service: service.to_string(),
            index: Mutex::new(()),
        };
        keychain.localise();
        Some(KeyStore {
            backend: Backend::Keychain(keychain),
        })
    }

    /// The SEC-17 file fallback: `dir` is created 0700 and must lie outside `data_dir`.
    pub fn files(dir: PathBuf, data_dir: &Path) -> io::Result<KeyStore> {
        // Checked before anything is created, so a refused folder leaves nothing behind.
        if resolved(&dir).starts_with(resolved(data_dir)) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "the key folder must be outside the app data folder (SEC-17)",
            ));
        }
        fs::create_dir_all(&dir)?;
        let resolved = dir.canonicalize()?;
        restrict(&resolved, 0o700)?;
        Ok(KeyStore {
            backend: Backend::Files(resolved),
        })
    }

    #[cfg(test)]
    pub(crate) fn memory() -> KeyStore {
        KeyStore {
            backend: Backend::Memory(Mutex::default()),
        }
    }

    pub fn kind(&self) -> KeyStoreKind {
        match self.backend {
            Backend::Files(_) | Backend::Unavailable => KeyStoreKind::UserFile,
            _ => KeyStoreKind::OsKeychain,
        }
    }

    /// Every secret held, by reference (unreadable ones are left out).
    pub fn entries(&self) -> Vec<KeysEntriesItem> {
        let refs: Vec<String> = match &self.backend {
            Backend::Keychain(keychain) => keychain.refs().into_iter().collect(),
            Backend::Files(dir) => fs::read_dir(dir)
                .map(|entries| {
                    let mut refs: Vec<String> = entries
                        .filter_map(|e| e.ok()?.file_name().into_string().ok())
                        .filter(|name| is_ref(name))
                        .collect();
                    refs.sort();
                    refs
                })
                .unwrap_or_default(),
            Backend::Unavailable => vec![],
            #[cfg(test)]
            Backend::Memory(map) => lock(map).keys().cloned().collect(),
        };
        refs.into_iter()
            .filter_map(|r| {
                let value = self.get(&r)?;
                Some(KeysEntriesItem {
                    r#ref: r,
                    value: Redacted::new(value),
                })
            })
            .take(ENTRIES_MAX)
            .collect()
    }

    fn get(&self, r: &str) -> Option<String> {
        let value = match &self.backend {
            Backend::Keychain(keychain) => keychain.get(r).ok().flatten(),
            Backend::Files(dir) => fs::read(dir.join(r)).ok().map(|bytes| encode(&bytes)),
            Backend::Unavailable => None,
            #[cfg(test)]
            Backend::Memory(map) => lock(map).get(r).cloned(),
        };
        value.filter(|value| is_value(value))
    }

    /// Store `value` under `r`, replacing any earlier value.
    pub fn put(&self, r: &str, value: &Redacted) -> bool {
        if !is_ref(r) || !is_value(value.reveal()) {
            return false;
        }
        match &self.backend {
            Backend::Keychain(keychain) => keychain.put(r, value.reveal()).is_ok(),
            Backend::Files(dir) => decode(value.reveal())
                .is_some_and(|bytes| write_private(&dir.join(r), &bytes).is_ok()),
            Backend::Unavailable => false,
            #[cfg(test)]
            Backend::Memory(map) => {
                lock(map).insert(r.to_string(), value.reveal().to_string());
                true
            }
        }
    }

    /// Delete the secret under `r`; deleting one not held succeeds.
    pub fn delete(&self, r: &str) -> bool {
        if !is_ref(r) {
            return false;
        }
        match &self.backend {
            Backend::Keychain(keychain) => keychain.delete(r).is_ok(),
            Backend::Files(dir) => match fs::remove_file(dir.join(r)) {
                Ok(()) => true,
                Err(error) => error.kind() == io::ErrorKind::NotFound,
            },
            Backend::Unavailable => false,
            #[cfg(test)]
            Backend::Memory(map) => {
                lock(map).remove(r);
                true
            }
        }
    }

    /// The `control.keys` frame for a starting core.
    pub fn keys_frame(&self) -> ToCore {
        ToCore::Keys(Keys {
            store: self.kind(),
            entries: self.entries(),
        })
    }

    /// The answer to a key request from the core (`control.key_result`), or `None` for any other frame.
    pub fn answer(&self, frame: &ToShell) -> Option<ToCore> {
        let (r, op, ok) = match frame {
            ToShell::KeyPut(KeyPut { r#ref, value }) => {
                (r#ref, KeyResultOp::Put, self.put(r#ref, value))
            }
            ToShell::KeyDelete(KeyDelete { r#ref }) => {
                (r#ref, KeyResultOp::Delete, self.delete(r#ref))
            }
            _ => return None,
        };
        Some(ToCore::KeyResult(KeyResult {
            r#ref: r.clone(),
            op,
            ok,
            store: self.kind(),
        }))
    }
}

// --- uninstall (PLT-24, G81) ------------------------------------------------------------------------------------

/// The keychain service and fallback folder name for the app's identifier: development builds keep their secrets
/// apart from an installed app's.
pub fn service_and_folder(identifier: &str, development: bool) -> (String, &'static str) {
    if development {
        (format!("{identifier}.dev"), "keys-dev")
    } else {
        (identifier.to_string(), "keys")
    }
}

/// What clearing the app's keys removed, or in a dry run would remove: references, the index and file names, never
/// a value.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Cleared {
    /// Keychain accounts: references and the index.
    pub keychain: Vec<String>,
    /// Files of the SEC-17 fallback folder.
    pub files: Vec<String>,
    /// What could not be removed (the uninstaller says so).
    pub failed: Vec<String>,
}

impl Cleared {
    pub fn ok(&self) -> bool {
        self.failed.is_empty()
    }

    fn merge(&mut self, other: Cleared) {
        self.keychain.extend(other.keychain);
        self.files.extend(other.files);
        self.failed.extend(other.failed);
    }

    /// The uninstaller's log line (JSON).
    pub fn report(&self, dry_run: bool) -> String {
        serde_json::json!({
            "dry_run": dry_run,
            "keychain": self.keychain,
            "files": self.files,
            "failed": self.failed,
        })
        .to_string()
    }
}

impl KeyStore {
    /// PLT-24: delete every secret this store holds for the app, and the keychain's index after them (so an
    /// interrupted run can be run again); with `dry_run`, only list them.
    pub fn clear(&self, dry_run: bool) -> Cleared {
        let mut cleared = Cleared::default();
        match &self.backend {
            Backend::Keychain(keychain) => {
                for account in keychain.accounts() {
                    let removed = dry_run || keychain.remove(&account).is_ok();
                    if removed {
                        cleared.keychain.push(account);
                    } else {
                        cleared.failed.push(format!("keychain {account}"));
                    }
                }
            }
            Backend::Files(dir) => {
                let mut names: Vec<String> = fs::read_dir(dir)
                    .map(|entries| {
                        entries
                            .filter_map(|e| e.ok()?.file_name().into_string().ok())
                            .filter(|name| is_ref(name.strip_suffix(".tmp").unwrap_or(name)))
                            .collect()
                    })
                    .unwrap_or_default();
                names.sort();
                for name in names {
                    let removed = dry_run
                        || match fs::remove_file(dir.join(&name)) {
                            Ok(()) => true,
                            Err(error) => error.kind() == io::ErrorKind::NotFound,
                        };
                    if removed {
                        cleared.files.push(name);
                    } else {
                        cleared.failed.push(format!("file {name}"));
                    }
                }
                if !dry_run {
                    let _ = fs::remove_dir(dir); // only when nothing else is left in it
                }
            }
            Backend::Unavailable => {}
            #[cfg(test)]
            Backend::Memory(map) => {
                let mut map = lock(map);
                cleared.keychain = map.keys().cloned().collect();
                if !dry_run {
                    map.clear();
                }
            }
        }
        cleared
    }
}

/// PLT-24, G81: the uninstaller's delete choice removes the app's keychain items (every reference under `service`
/// and the index) and the SEC-17 fallback files in `keys_dir`, which is never created here; `dry_run` lists them.
pub fn uninstall_keys(service: &str, keys_dir: &Path, dry_run: bool) -> Cleared {
    let mut cleared = Cleared::default();
    if let Some(store) = KeyStore::keychain(service) {
        cleared.merge(store.clear(dry_run));
    }
    if keys_dir.is_dir() {
        let files = KeyStore {
            backend: Backend::Files(keys_dir.to_path_buf()),
        };
        cleared.merge(files.clear(dry_run));
    }
    cleared
}

/// A request to clear the app's keys: `--uninstall-keys [--dry-run] [--keys-dir DIR]`.
#[derive(Debug, PartialEq, Eq)]
pub struct UninstallKeys {
    pub dry_run: bool,
    pub keys_dir: Option<PathBuf>,
}

/// The `--uninstall-keys` request in the shell's arguments, or `None` when it is not one (the app then starts).
pub fn uninstall_keys_args(args: &[String]) -> Option<UninstallKeys> {
    if !args.iter().any(|a| a == "--uninstall-keys") {
        return None;
    }
    let keys_dir = args
        .iter()
        .position(|a| a == "--keys-dir")
        .and_then(|at| args.get(at + 1))
        .filter(|dir| !dir.is_empty())
        .map(PathBuf::from);
    Some(UninstallKeys {
        dry_run: args.iter().any(|a| a == "--dry-run"),
        keys_dir,
    })
}

/// The folder above the fallback key folder as the app resolves it, for when the uninstaller does not name it: the
/// local `%LOCALAPPDATA%` on Windows (never the roaming `%APPDATA%`, which a roaming profile copies to other machines;
/// Tauri's `local_data_dir`), `~/Library/Application Support` on macOS, `$XDG_CONFIG_HOME` or `~/.config` elsewhere
/// (Tauri's `config_dir`).
pub fn default_config_dir() -> Option<PathBuf> {
    let var = |name: &str| {
        std::env::var_os(name)
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
    };
    if cfg!(windows) {
        var("LOCALAPPDATA")
    } else if cfg!(target_os = "macos") {
        var("HOME").map(|home| home.join("Library/Application Support"))
    } else {
        var("XDG_CONFIG_HOME").or_else(|| var("HOME").map(|home| home.join(".config")))
    }
}

/// `jana-shell --uninstall-keys ...`: clears the keys, prints the report and returns the exit code (0 when everything
/// was removed, 1 when something was not, 64 when the fallback folder cannot be found).
pub fn uninstall_keys_main(identifier: &str, development: bool, request: &UninstallKeys) -> i32 {
    let (service, folder) = service_and_folder(identifier, development);
    let Some(keys_dir) = request
        .keys_dir
        .clone()
        .or_else(|| default_config_dir().map(|config| config.join("jana").join(folder)))
    else {
        eprintln!("--uninstall-keys: name the key folder with --keys-dir");
        return 64;
    };
    let cleared = uninstall_keys(&service, &keys_dir, request.dry_run);
    let _ = writeln!(io::stdout(), "{}", cleared.report(request.dry_run));
    if cleared.ok() { 0 } else { 1 }
}

#[cfg(test)]
fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// The platform's keychain service; `None` where it cannot be reached.
fn os_store() -> Option<Arc<keyring_core::CredentialStore>> {
    #[cfg(target_os = "macos")]
    let store: Arc<keyring_core::CredentialStore> =
        apple_native_keyring_store::keychain::Store::new().ok()?;
    #[cfg(windows)]
    let store: Arc<keyring_core::CredentialStore> =
        windows_native_keyring_store::Store::new().ok()?;
    #[cfg(all(unix, not(target_os = "macos")))]
    let store: Arc<keyring_core::CredentialStore> =
        zbus_secret_service_keyring_store::Store::new().ok()?;
    Some(store)
}

/// A keychain failure, without its detail: keychain errors can carry the bytes they failed on, so none is kept.
#[derive(Debug)]
struct Failed;

/// The modifiers every item is built with (`PERSISTENCE`).
fn modifiers() -> Option<std::collections::HashMap<&'static str, &'static str>> {
    PERSISTENCE.map(|(key, value)| std::collections::HashMap::from([(key, value)]))
}

impl Keychain {
    fn entry(&self, account: &str) -> Result<keyring_core::Entry, Failed> {
        self.store
            .build(&self.service, account, modifiers().as_ref())
            .map_err(|_| Failed)
    }

    /// Items an earlier build wrote with another persistence (Windows: enterprise, which roams) are written again
    /// with `PERSISTENCE`, value unchanged; an item that cannot be read or rewritten is left as it was.
    fn localise(&self) {
        let Some((key, wanted)) = PERSISTENCE else {
            return;
        };
        let _guard = self.index.lock().unwrap_or_else(|p| p.into_inner());
        let mut accounts: Vec<String> = self.refs().into_iter().collect();
        accounts.push(INDEX_ACCOUNT.to_string());
        for account in accounts {
            let Ok(entry) = self.entry(&account) else {
                continue;
            };
            let current = entry
                .get_attributes()
                .ok()
                .and_then(|a| a.get(key).cloned());
            if current.is_none_or(|value| value.eq_ignore_ascii_case(wanted)) {
                continue; // not held, or already local
            }
            if let Ok(value) = entry.get_password() {
                let _ = entry.set_password(&value);
            }
        }
    }

    fn get(&self, account: &str) -> Result<Option<String>, Failed> {
        match self.entry(account)?.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring_core::Error::NoEntry) => Ok(None),
            Err(_) => Err(Failed),
        }
    }

    fn refs(&self) -> BTreeSet<String> {
        self.get(INDEX_ACCOUNT)
            .ok()
            .flatten()
            .map(|text| {
                text.lines()
                    .filter(|r| is_ref(r))
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default()
    }

    fn write_index(&self, refs: &BTreeSet<String>) -> Result<(), Failed> {
        let entry = self.entry(INDEX_ACCOUNT)?;
        if refs.is_empty() {
            return match entry.delete_credential() {
                Ok(()) | Err(keyring_core::Error::NoEntry) => Ok(()),
                Err(_) => Err(Failed),
            };
        }
        let text: Vec<&str> = refs.iter().map(String::as_str).collect();
        entry.set_password(&text.join("\n")).map_err(|_| Failed)
    }

    /// Every account the app holds under its service: the index's references, any reference the keychain finds
    /// under the service where it can search (macOS, the Secret Service), and the index itself, last.
    fn accounts(&self) -> Vec<String> {
        let mut refs = self.refs();
        let spec = std::collections::HashMap::from([("service", self.service.as_str())]);
        let mut index = self.get(INDEX_ACCOUNT).ok().flatten().is_some();
        if let Ok(found) = self.store.search(&spec) {
            for (service, account) in found.iter().filter_map(keyring_core::Entry::get_specifiers) {
                if service != self.service {
                    continue;
                }
                if account == INDEX_ACCOUNT {
                    index = true;
                } else if is_ref(&account) {
                    refs.insert(account);
                }
            }
        }
        let mut accounts: Vec<String> = refs.into_iter().collect();
        if index {
            accounts.push(INDEX_ACCOUNT.to_string());
        }
        accounts
    }

    /// Delete one account's item; one not held succeeds.
    fn remove(&self, account: &str) -> Result<(), Failed> {
        match self.entry(account)?.delete_credential() {
            Ok(()) | Err(keyring_core::Error::NoEntry) => Ok(()),
            Err(_) => Err(Failed),
        }
    }

    fn put(&self, r: &str, value: &str) -> Result<(), Failed> {
        let _guard = self.index.lock().unwrap_or_else(|p| p.into_inner());
        self.entry(r)?.set_password(value).map_err(|_| Failed)?;
        let mut refs = self.refs();
        if refs.insert(r.to_string()) {
            self.write_index(&refs)?;
        }
        Ok(())
    }

    fn delete(&self, r: &str) -> Result<(), Failed> {
        let _guard = self.index.lock().unwrap_or_else(|p| p.into_inner());
        match self.entry(r)?.delete_credential() {
            Ok(()) | Err(keyring_core::Error::NoEntry) => {}
            Err(_) => return Err(Failed),
        }
        let mut refs = self.refs();
        if refs.remove(r) {
            self.write_index(&refs)?;
        }
        Ok(())
    }
}

/// `path` with its deepest existing ancestor resolved (links followed), for containment checks before creating it.
fn resolved(path: &Path) -> PathBuf {
    let mut rest = vec![];
    let mut base = path;
    loop {
        if let Ok(real) = base.canonicalize() {
            return rest.iter().rev().fold(real, |acc, part| acc.join(part));
        }
        match (base.parent(), base.file_name()) {
            (Some(parent), Some(name)) => {
                rest.push(name.to_owned());
                base = parent;
            }
            _ => return path.to_path_buf(),
        }
    }
}

/// Write `bytes` to `path` readable only by the user (0600), through a temporary file, as the core's `FileKeyStore`
/// does.
fn write_private(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut temporary = path.as_os_str().to_owned();
    temporary.push(".tmp");
    let temporary = PathBuf::from(temporary);
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = options.open(&temporary).and_then(|mut file| {
        file.write_all(bytes)?;
        file.sync_all()
    });
    let result = result
        .and_then(|()| restrict(&temporary, 0o600))
        .and_then(|()| fs::rename(&temporary, path));
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(unix)]
fn restrict(path: &Path, mode: u32) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(mode))
}

/// On Windows the folder sits in the user's own profile, which only that user (and administrators) can read.
#[cfg(not(unix))]
fn restrict(_path: &Path, _mode: u32) -> io::Result<()> {
    Ok(())
}

const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/// base64url without padding, as the control channel carries secrets.
fn encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let value = chunk
            .iter()
            .enumerate()
            .fold(0u32, |acc, (i, b)| acc | (u32::from(*b) << (16 - 8 * i)));
        for i in 0..=chunk.len() {
            out.push(char::from(
                ALPHABET[((value >> (18 - 6 * i)) & 63) as usize],
            ));
        }
    }
    out
}

fn decode(text: &str) -> Option<Vec<u8>> {
    if text.len() % 4 == 1 {
        return None;
    }
    let mut out = Vec::with_capacity(text.len() * 3 / 4);
    for chunk in text.as_bytes().chunks(4) {
        let mut value = 0u32;
        for (i, c) in chunk.iter().enumerate() {
            let digit = ALPHABET.iter().position(|a| a == c)? as u32;
            value |= digit << (18 - 6 * i);
        }
        for i in 0..chunk.len() - 1 {
            out.push((value >> (16 - 8 * i)) as u8);
        }
    }
    // Only the canonical spelling: unused low bits must be zero.
    (encode(&out) == text).then_some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "jana-keys-{name}-{}-{}",
            std::process::id(),
            crate::launch::Token::new().reveal()
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn put_frame(r: &str, value: &str) -> ToShell {
        ToShell::KeyPut(KeyPut {
            r#ref: r.into(),
            value: Redacted::new(value),
        })
    }

    #[test]
    fn base64url_round_trips_and_refuses_odd_spellings() {
        for bytes in [&b""[..], b"f", b"fo", b"foo", b"foob", b"\xff\xfe\x00"] {
            assert_eq!(decode(&encode(bytes)).as_deref(), Some(bytes));
        }
        assert_eq!(encode(b"dcr_example"), "ZGNyX2V4YW1wbGU");
        assert_eq!(decode("ZGNyX2V4YW1wbGU").unwrap(), b"dcr_example");
        assert_eq!(decode("a"), None);
        assert_eq!(decode("ab+/"), None);
        assert_eq!(decode("Zh"), None); // non-zero unused bits
    }

    #[test]
    fn references_follow_the_contract() {
        assert!(is_ref("jana.device-db"));
        assert!(is_ref("jana.service-credential.ed25519"));
        for bad in [
            "jana.",
            "jana.a",
            "device-db",
            "jana.Upper",
            "jana.a/b",
            "jana.a\\b",
            "index",
        ] {
            assert!(!is_ref(bad), "{bad}");
        }
        assert!(!is_ref(&format!("jana.{}", "a".repeat(77))));
    }

    #[test]
    fn answers_follow_every_request_in_order() {
        let store = KeyStore::memory();
        let requests = [
            put_frame("jana.device-db", "ZGJfa2V5"),
            put_frame("jana.service-credential.id", "ZGNyX2V4YW1wbGU"),
            ToShell::KeyDelete(KeyDelete {
                r#ref: "jana.device-db".into(),
            }),
            put_frame("not-a-ref", "ZGJfa2V5"),
        ];
        let answers: Vec<_> = requests
            .iter()
            .map(|frame| match store.answer(frame) {
                Some(ToCore::KeyResult(result)) => (result.r#ref, result.op, result.ok),
                other => panic!("{other:?}"),
            })
            .collect();
        assert_eq!(
            answers,
            [
                ("jana.device-db".into(), KeyResultOp::Put, true),
                ("jana.service-credential.id".into(), KeyResultOp::Put, true),
                ("jana.device-db".into(), KeyResultOp::Delete, true),
                ("not-a-ref".into(), KeyResultOp::Put, false),
            ]
        );
        let ToCore::Keys(keys) = store.keys_frame() else {
            panic!()
        };
        assert_eq!(keys.store, KeyStoreKind::OsKeychain);
        assert_eq!(keys.entries.len(), 1);
        assert_eq!(keys.entries[0].r#ref, "jana.service-credential.id");
        assert_eq!(keys.entries[0].value.reveal(), "ZGNyX2V4YW1wbGU");
        assert!(
            store
                .answer(&ToShell::Bye(crate::control::Bye {}))
                .is_none()
        );
    }

    #[test]
    fn file_fallback_keeps_private_files_outside_the_data_folder() {
        let root = scratch("files");
        let data = root.join("data");
        fs::create_dir_all(&data).unwrap();
        assert!(KeyStore::files(data.join("keys"), &data).is_err());
        // Neither keychain nor folder: nothing held, every request fails (the core then reports it degraded).
        let nowhere = KeyStore {
            backend: Backend::Unavailable,
        };
        assert_eq!(nowhere.kind(), KeyStoreKind::UserFile);
        assert!(!nowhere.put("jana.device-db", &Redacted::new("ZGJfa2V5")));
        assert!(nowhere.entries().is_empty());
        let dir = root.join("config/jana/keys");
        let store = KeyStore::files(dir.clone(), &data).unwrap();
        assert_eq!(store.kind(), KeyStoreKind::UserFile);
        assert!(store.put("jana.device-db", &Redacted::new("ZGJfa2V5")));
        assert!(store.put(
            "jana.service-credential.id",
            &Redacted::new("ZGNyX2V4YW1wbGU")
        ));
        assert!(!store.put("jana.bad", &Redacted::new("not base64!")));
        // The core's FileKeyStore layout: the raw secret, one file per reference, and nothing else.
        assert_eq!(fs::read(dir.join("jana.device-db")).unwrap(), b"db_key");
        let mut names: Vec<_> = fs::read_dir(&dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .collect();
        names.sort();
        assert_eq!(names, ["jana.device-db", "jana.service-credential.id"]);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = |p: &Path| fs::metadata(p).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode(&dir), 0o700);
            for name in &names {
                assert_eq!(mode(&dir.join(name)), 0o600, "{name}");
            }
        }
        assert!(fs::read_dir(&data).unwrap().next().is_none());
        // A restart reads the same secrets back; a delete removes one, and deleting it again still succeeds.
        let again = KeyStore::files(dir.clone(), &data).unwrap();
        let ToCore::Keys(keys) = again.keys_frame() else {
            panic!()
        };
        assert_eq!(keys.store, KeyStoreKind::UserFile);
        let held: Vec<_> = keys
            .entries
            .iter()
            .map(|e| (e.r#ref.as_str(), e.value.reveal()))
            .collect();
        assert_eq!(
            held,
            [
                ("jana.device-db", "ZGJfa2V5"),
                ("jana.service-credential.id", "ZGNyX2V4YW1wbGU")
            ]
        );
        assert!(again.delete("jana.device-db"));
        assert!(again.delete("jana.device-db"));
        assert!(!dir.join("jana.device-db").exists());
        assert_eq!(again.entries().len(), 1);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn values_never_show_in_debug_output() {
        let root = scratch("debug");
        let store = KeyStore::files(root.join("keys"), &root.join("data")).unwrap();
        assert!(store.put("jana.device-db", &Redacted::new("c2VjcmV0X2NhbmFyeQ")));
        let shown = format!(
            "{store:?} {:?} {:?} {:?}",
            store.keys_frame(),
            store.entries(),
            store.answer(&put_frame("jana.device-db", "c2VjcmV0X2NhbmFyeQ"))
        );
        assert!(!shown.contains("c2VjcmV0X2NhbmFyeQ"), "{shown}");
        assert!(shown.contains("jana.device-db"));
        fs::remove_dir_all(root).unwrap();
    }

    /// PLT-24: the uninstaller's delete choice clears every key the app holds; a dry run lists them and removes
    /// nothing; nothing outside the app's references is touched, and the fallback folder goes once it is empty.
    #[test]
    fn test_plt24_uninstall_clears_the_apps_keys() {
        let store = KeyStore::memory();
        assert!(store.put("jana.device-db", &Redacted::new("ZGJfa2V5")));
        assert!(store.put("jana.profile.synthetic", &Redacted::new("c3ludGg")));
        let listed = store.clear(true);
        assert_eq!(
            listed.keychain,
            ["jana.device-db", "jana.profile.synthetic"]
        );
        assert_eq!(store.entries().len(), 2, "a dry run removes nothing");
        let cleared = store.clear(false);
        assert!(cleared.ok() && cleared.keychain.len() == 2);
        assert!(store.entries().is_empty());

        let root = scratch("uninstall");
        let data = root.join("data");
        let dir = root.join("config/jana/keys");
        let files = KeyStore::files(dir.clone(), &data).unwrap();
        assert!(files.put("jana.device-db", &Redacted::new("ZGJfa2V5")));
        fs::write(dir.join("jana.install-marker.tmp"), b"half written").unwrap();
        let listed = files.clear(true);
        assert_eq!(listed.files, ["jana.device-db", "jana.install-marker.tmp"]);
        assert!(dir.join("jana.device-db").exists());
        fs::write(dir.join("notes.txt"), b"not the app's").unwrap();
        let cleared = files.clear(false);
        assert!(cleared.ok(), "{cleared:?}");
        assert!(!dir.join("jana.device-db").exists() && dir.join("notes.txt").exists());
        fs::remove_file(dir.join("notes.txt")).unwrap();
        assert!(files.clear(false).files.is_empty());
        assert!(!dir.exists(), "the empty fallback folder is removed");
        // The shell entry point on a folder alone (the keychain part is the ignored test below).
        let dir = root.join("config/jana/keys-again");
        let files = KeyStore::files(dir.clone(), &data).unwrap();
        assert!(files.put(
            "jana.service-credential.id",
            &Redacted::new("ZGNyX2V4YW1wbGU")
        ));
        let report = KeyStore {
            backend: Backend::Files(dir.clone()),
        }
        .clear(false)
        .report(false);
        let report: serde_json::Value = serde_json::from_str(&report).unwrap();
        assert_eq!(report["files"][0], "jana.service-credential.id");
        assert!(
            !report.to_string().contains("ZGNyX2V4YW1wbGU"),
            "no value in the report"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn uninstall_keys_arguments() {
        let args = |list: &[&str]| list.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert_eq!(uninstall_keys_args(&args(&["jana-shell"])), None);
        assert_eq!(
            uninstall_keys_args(&args(&["jana-shell", "--uninstall-keys", "--dry-run"])),
            Some(UninstallKeys {
                dry_run: true,
                keys_dir: None
            })
        );
        assert_eq!(
            uninstall_keys_args(&args(&[
                "Jana.exe",
                "--uninstall-keys",
                "--keys-dir",
                "C:\\Users\\a\\AppData\\Local\\jana\\keys"
            ])),
            Some(UninstallKeys {
                dry_run: false,
                keys_dir: Some(PathBuf::from("C:\\Users\\a\\AppData\\Local\\jana\\keys"))
            })
        );
        assert_eq!(
            service_and_folder("app.jana.desktop", false),
            ("app.jana.desktop".into(), "keys")
        );
        assert_eq!(
            service_and_folder("app.jana.desktop", true),
            ("app.jana.desktop.dev".into(), "keys-dev")
        );
        assert!(default_config_dir().is_some_and(|dir| dir.is_absolute()));
    }

    /// The real OS keychain, cleared as the uninstaller clears it (dry run first): it may ask the developer for
    /// access, so it runs only on request (`cargo test -- --ignored keychain_uninstall`).
    #[test]
    #[ignore]
    fn keychain_uninstall() {
        let service = format!("app.jana.desktop.test-uninstall-{}", std::process::id());
        let store = KeyStore::keychain(&service).expect("a keychain service");
        assert!(store.put("jana.test-a", &Redacted::new("dGVzdA")));
        assert!(store.put("jana.test-b", &Redacted::new("dGVzdA")));
        let nowhere = std::env::temp_dir().join(format!("jana-no-keys-{}", std::process::id()));
        let listed = uninstall_keys(&service, &nowhere, true);
        assert_eq!(listed.keychain, ["jana.test-a", "jana.test-b", "index"]);
        assert_eq!(KeyStore::keychain(&service).unwrap().entries().len(), 2);
        let cleared = uninstall_keys(&service, &nowhere, false);
        assert!(cleared.ok(), "{cleared:?}");
        let again = KeyStore::keychain(&service).unwrap();
        assert!(again.entries().is_empty());
        assert!(uninstall_keys(&service, &nowhere, true).keychain.is_empty());
        assert!(!nowhere.exists());
    }

    /// The real OS keychain: it may ask the developer for access, so it runs only on request
    /// (`cargo test -- --ignored keychain_round_trip`).
    #[test]
    #[ignore]
    fn keychain_round_trip() {
        let service = format!("app.jana.desktop.test-{}", std::process::id());
        let store = KeyStore::keychain(&service).expect("a keychain service");
        assert!(store.put("jana.test-secret", &Redacted::new("dGVzdA")));
        let again = KeyStore::keychain(&service).unwrap();
        assert_eq!(again.entries().len(), 1);
        assert!(again.delete("jana.test-secret"));
        assert!(again.entries().is_empty());
    }
}
