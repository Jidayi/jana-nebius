//! An offline install is handed off only after core and runtime shutdown (PLT-15).
//!
//! The installer's bytes are hashed through the same open handle the hand-off keeps until the installer has started,
//! so what runs is what was checked (SEC-15). On Windows the handle denies every other writer and deleter while it is
//! open (share mode read only): an `.exe` is mapped by `CreateProcess` before the handle closes, so no one can swap it
//! between the check and the launch. A replaced AppImage is written from the hashed handle itself, and the written
//! copy is hashed again before it replaces the running app. Elsewhere the operating system's installer checks the
//! package's own signature as it opens it (macOS Installer for a `.pkg`, Gatekeeper for the app in a `.dmg`).
use crate::control::{UpdateInstall, UpdateInstallAction};
use sha2::{Digest, Sha256};
use std::ffi::OsString;
use std::fs::{File, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[derive(Debug, PartialEq)]
pub struct InstallerCommand {
    pub program: PathBuf,
    pub args: Vec<OsString>,
}

/// A checked installer: the command that starts it and the handle its bytes were hashed through, which must stay open
/// until the installer has started.
#[derive(Debug)]
pub struct Verified {
    pub command: InstallerCommand,
    file: File,
}

/// The installer opened for the check: on Windows no other process may write, rename or delete it while the handle
/// is open (`FILE_SHARE_READ` only).
fn open_held(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_SHARE_READ: u32 = 0x1;
        options.share_mode(FILE_SHARE_READ);
    }
    options.open(path)
}

fn digest(file: &mut File) -> io::Result<String> {
    file.seek(SeekFrom::Start(0))?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let size = file.read(&mut buffer)?;
        if size == 0 {
            break;
        }
        digest.update(&buffer[..size]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

pub fn command(data: &Path, plan: &UpdateInstall, os: &str) -> io::Result<InstallerCommand> {
    verify(data, plan, os).map(|verified| verified.command)
}

/// The plan's installer, checked: inside the update folders, the planned size and digest, read through the one
/// handle `Verified` keeps.
pub fn verify(data: &Path, plan: &UpdateInstall, os: &str) -> io::Result<Verified> {
    let refuse = || io::Error::new(io::ErrorKind::InvalidData, "invalid update handoff");
    let branch = match plan.action {
        UpdateInstallAction::Update => "staged",
        UpdateInstallAction::Rollback => "installers",
    };
    if plan.version.is_empty()
        || !plan
            .version
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
        || plan.version == "."
        || plan.version == ".."
    {
        return Err(refuse());
    }
    let updates = data.join("updates").canonicalize()?;
    let expected = updates.join(branch).join(&plan.version).canonicalize()?;
    let installer = Path::new(&plan.installer).canonicalize()?;
    if !expected.starts_with(&updates) || installer.parent() != Some(expected.as_path()) {
        return Err(refuse());
    }
    let mut file = open_held(&installer)?;
    let metadata = file.metadata()?; // of the opened file, not of whatever the path names later
    if !metadata.is_file() || metadata.len() != plan.size_bytes || digest(&mut file)? != plan.sha256
    {
        return Err(refuse());
    }
    let extension = installer
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let command = match (os, extension.as_str()) {
        ("windows", "exe") => InstallerCommand {
            program: installer,
            args: vec![],
        },
        ("windows", "msi") => InstallerCommand {
            program: PathBuf::from(
                std::env::var_os("WINDIR").unwrap_or_else(|| "C:\\Windows".into()),
            )
            .join("System32/msiexec.exe"),
            args: vec!["/i".into(), installer.into_os_string()],
        },
        ("macos", "pkg" | "dmg") => InstallerCommand {
            program: "/usr/bin/open".into(),
            args: vec![installer.into_os_string()],
        },
        ("linux", "deb" | "rpm") => InstallerCommand {
            program: "/usr/bin/xdg-open".into(),
            args: vec![installer.into_os_string()],
        },
        ("linux", "appimage") => InstallerCommand {
            program: installer,
            args: vec![],
        },
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "unsupported offline installer",
            ));
        }
    };
    Ok(Verified { command, file })
}

pub fn launch(data: &Path, plan: &UpdateInstall) -> io::Result<()> {
    let os = if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    };
    let Verified {
        mut command,
        mut file,
    } = verify(data, plan, os)?;
    if os == "linux"
        && command
            .program
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("AppImage"))
    {
        let original = PathBuf::from(std::env::var_os("APPIMAGE").ok_or_else(|| {
            io::Error::new(io::ErrorKind::Unsupported, "not running as an AppImage")
        })?)
        .canonicalize()?;
        if original.starts_with(data.join("updates").canonicalize()?) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "cannot overwrite a cached installer",
            ));
        }
        replace_appimage(&mut file, &plan.sha256, &original)?;
        command.program = original;
    }
    Command::new(command.program)
        .args(command.args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    drop(file); // only now: the installer has started from the bytes that were checked
    Ok(())
}

/// The running AppImage replaced by the checked one: written from the handle that was hashed, the written copy hashed
/// again, and only then renamed over `target`.
fn replace_appimage(source: &mut File, sha256: &str, target: &Path) -> io::Result<()> {
    let pending = target.with_extension("AppImage.jana-update");
    let result = (|| {
        source.seek(SeekFrom::Start(0))?;
        let mut output = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&pending)?;
        io::copy(source, &mut output)?;
        output.flush()?;
        output.sync_all()?;
        if digest(&mut output)? != sha256 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "the written installer did not verify",
            ));
        }
        drop(output);
        std::fs::set_permissions(&pending, target.metadata()?.permissions())?;
        std::fs::rename(&pending, target)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(pending);
    }
    result
}

pub fn record_failure(data: &Path) {
    let path = data.join("updates/update-state.json");
    if let Ok(bytes) = std::fs::read(&path)
        && let Ok(mut state) = serde_json::from_slice::<serde_json::Value>(&bytes)
    {
        state["failure_code"] = "installer_launch_failed".into();
        let pending = path.with_extension("json.partial");
        if let Ok(bytes) = serde_json::to_vec(&state)
            && std::fs::write(&pending, bytes).is_ok()
        {
            let _ = std::fs::rename(pending, path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn verified_handoff_is_contained_and_uses_no_shell() {
        let root = std::env::temp_dir().join(format!(
            "jana-update-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let folder = root.join("updates/staged/1.1.0");
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join("jana.exe");
        std::fs::write(&path, b"synthetic installer").unwrap();
        let mut plan = UpdateInstall {
            installer: path.to_string_lossy().into(),
            sha256: format!("{:x}", Sha256::digest(b"synthetic installer")),
            size_bytes: 19,
            version: "1.1.0".into(),
            action: UpdateInstallAction::Update,
        };
        let cmd = command(&root, &plan, "windows").unwrap();
        assert_eq!(cmd.program, path.canonicalize().unwrap());
        assert!(cmd.args.is_empty());
        plan.sha256 = "0".repeat(64);
        assert!(command(&root, &plan, "windows").is_err());
        plan.installer = root.join("outside.exe").to_string_lossy().into();
        std::fs::write(&plan.installer, b"synthetic installer").unwrap();
        assert!(command(&root, &plan, "windows").is_err());
        std::fs::remove_dir_all(root).unwrap();
    }

    fn staged(name: &str, file: &str, bytes: &[u8]) -> (PathBuf, PathBuf, UpdateInstall) {
        let root = std::env::temp_dir().join(format!(
            "jana-update-{name}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let folder = root.join("updates/staged/1.1.0");
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join(file);
        std::fs::write(&path, bytes).unwrap();
        let plan = UpdateInstall {
            installer: path.to_string_lossy().into(),
            sha256: format!("{:x}", Sha256::digest(bytes)),
            size_bytes: bytes.len() as u64,
            version: "1.1.0".into(),
            action: UpdateInstallAction::Update,
        };
        (root, path, plan)
    }

    /// SEC-15: what is launched is what was hashed. The check reads through the handle the hand-off keeps; bytes
    /// changed behind it are never the ones installed.
    #[test]
    fn test_sec15_installer_hashed_through_the_launch_handle() {
        let (root, path, plan) = staged(
            "held",
            "Jana.AppImage",
            b"synthetic appimage, version 1.1.0",
        );
        let mut verified = verify(&root, &plan, "linux").unwrap();
        assert_eq!(verified.command.program, path.canonicalize().unwrap());
        // Someone replaces the installer after the check (on Unix nothing stops the rename; Windows refuses it while
        // the handle is open, which the Windows runner's shell suite covers).
        let swapped = path.with_extension("swap");
        std::fs::write(&swapped, b"other bytes of the same length!!!").unwrap();
        std::fs::rename(&swapped, &path).unwrap();
        let running = root.join("Jana.AppImage");
        std::fs::write(&running, b"the running app").unwrap();
        replace_appimage(&mut verified.file, &plan.sha256, &running).unwrap();
        assert_eq!(
            std::fs::read(&running).unwrap(),
            b"synthetic appimage, version 1.1.0",
            "the checked bytes replace the app, not the swapped file"
        );
        // A handle whose bytes no longer match is refused and leaves the running app as it was.
        std::fs::write(&running, b"the running app").unwrap();
        let mut other = open_held(&path).unwrap();
        assert!(replace_appimage(&mut other, &plan.sha256, &running).is_err());
        assert_eq!(std::fs::read(&running).unwrap(), b"the running app");
        assert!(!running.with_extension("AppImage.jana-update").exists());
        // And a fresh check of the swapped file fails.
        assert!(verify(&root, &plan, "linux").is_err());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn test_sec15_windows_installer_locked_while_held() {
        let (root, path, plan) = staged("locked", "Jana_setup.exe", b"synthetic installer");
        let verified = verify(&root, &plan, "windows").unwrap();
        assert!(
            std::fs::OpenOptions::new().write(true).open(&path).is_err(),
            "no writer while held"
        );
        assert!(
            std::fs::rename(&path, path.with_extension("moved")).is_err(),
            "no rename while held"
        );
        assert!(std::fs::remove_file(&path).is_err(), "no delete while held");
        assert!(
            std::fs::read(&path).is_ok(),
            "readers (the installer itself) still open it"
        );
        drop(verified);
        std::fs::remove_dir_all(root).unwrap();
    }
}
