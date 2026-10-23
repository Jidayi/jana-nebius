//! Where the app keeps its data on this device (DAT-01, SEC-17, PLT-24).
//!
//! Learner data, models, packs and caches live in the user's *local* application data folder (Tauri's
//! `app_local_data_dir`: `%LOCALAPPDATA%` on Windows), never the roaming one: a roaming profile copies `%APPDATA%` to a
//! server and to every machine the account signs in to, which would carry minors' learner records, gigabytes of
//! models and the SEC-17 key files off the device. On macOS and Linux the two folders are the same, so nothing moves.
//!
//! Builds before this one kept everything in the roaming folder. The first start of this build moves it, once:
//!
//! 1. On one volume the roaming folder is renamed, whole, to a staging folder beside the local one (atomic: either
//!    nothing moved or all of it did). Across volumes (a redirected `%APPDATA%`) it is copied to the staging folder,
//!    every file synced, and the copy compared byte for byte with the original; only then is the verified marker
//!    written and the original removed. Nothing is deleted before the copy has verified.
//! 2. Each entry of the staging folder is renamed into the local folder (the same volume, so each is atomic). An
//!    entry the local folder already holds (for example the webview's own data) is never overwritten: it stays in
//!    staging, the local data wins, and nothing is lost.
//!
//! Every step can be interrupted and is finished at the next start: a staging folder without its marker while the
//! roaming folder still exists is an unfinished copy and is made again from the untouched original; one with the
//! marker, or with the roaming folder gone (it was renamed), is complete and its moves resume.

use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};

/// Written into the staging folder once it holds a verified, complete copy of the roaming folder.
pub const VERIFIED: &str = ".jana-migration-verified";
const STAGING_SUFFIX: &str = ".jana-migrating";

/// What one start's migration did.
#[derive(Debug, PartialEq, Eq)]
pub enum Moved {
    /// There was nothing to move (a fresh install, or the move finished earlier).
    Nothing,
    /// Everything moved; `copied` when it had to be copied across volumes.
    All { copied: bool },
    /// Everything that could move did; these entries were already in the local folder, so the roaming copies stay
    /// in the staging folder untouched.
    Kept(Vec<String>),
}

/// The staging folder for `local`: its sibling, so on the local folder's volume.
pub fn staging(local: &Path) -> PathBuf {
    let mut name = local.file_name().unwrap_or_default().to_os_string();
    name.push(STAGING_SUFFIX);
    local.with_file_name(name)
}

/// The data folder this start uses: `local`, after moving `roaming` into it when they differ. When the move fails
/// before anything left the roaming folder (a locked file, a full disk), this start keeps using `roaming` and the
/// next start tries again; a failure after that is returned, so the app never starts on half its data.
pub fn resolve(roaming: Option<&Path>, local: &Path) -> io::Result<PathBuf> {
    let Some(roaming) = roaming.filter(|r| !same(r, local)) else {
        return Ok(local.to_path_buf());
    };
    match migrate(roaming, local) {
        Ok(_) => Ok(local.to_path_buf()),
        Err(error) => {
            let staged = staging(local);
            if roaming.is_dir() && !staged.join(VERIFIED).exists() {
                let _ = fs::remove_dir_all(&staged); // an unfinished copy; the original is intact
                Ok(roaming.to_path_buf())
            } else {
                Err(error)
            }
        }
    }
}

fn same(a: &Path, b: &Path) -> bool {
    a == b || matches!((a.canonicalize(), b.canonicalize()), (Ok(x), Ok(y)) if x == y)
}

/// Move `roaming` into `local` (module docs). Safe to call at every start.
pub fn migrate(roaming: &Path, local: &Path) -> io::Result<Moved> {
    let staged = staging(local);
    let mut copied = false;
    if roaming.is_dir() {
        if staged.exists() && !staged.join(VERIFIED).exists() {
            fs::remove_dir_all(&staged)?; // an interrupted copy: the original is still whole
        }
        if !staged.exists() {
            if let Some(parent) = staged.parent() {
                fs::create_dir_all(parent)?;
            }
            if fs::rename(roaming, &staged).is_err() {
                copy_tree(roaming, &staged)?;
                if !same_tree(roaming, &staged)? {
                    let _ = fs::remove_dir_all(&staged);
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "the copy did not verify",
                    ));
                }
                copied = true;
            }
            write_marker(&staged)?;
        }
        if roaming.exists() {
            fs::remove_dir_all(roaming)?; // only ever after the verified marker
        }
    }
    if !staged.is_dir() {
        return Ok(Moved::Nothing);
    }
    write_marker(&staged)?; // the roaming folder is gone: the staging folder is the only copy
    fs::create_dir_all(local)?;
    let mut kept = vec![];
    let mut names: Vec<_> = fs::read_dir(&staged)?
        .filter_map(|e| e.ok().map(|e| e.file_name()))
        .collect();
    names.sort();
    for name in names {
        if name == VERIFIED {
            continue;
        }
        let target = local.join(&name);
        if fs::symlink_metadata(&target).is_ok() {
            kept.push(name.to_string_lossy().into_owned());
            continue;
        }
        fs::rename(staged.join(&name), target)?;
    }
    if !kept.is_empty() {
        return Ok(Moved::Kept(kept));
    }
    fs::remove_file(staged.join(VERIFIED))?;
    fs::remove_dir(&staged)?;
    Ok(Moved::All { copied })
}

fn write_marker(staged: &Path) -> io::Result<()> {
    let marker = staged.join(VERIFIED);
    if !marker.exists() {
        let file = File::create(&marker)?;
        file.sync_all()?;
    }
    Ok(())
}

/// A copy of `from` at `to`, every file synced. Links are refused: an application data folder holds none, and
/// following one could copy something that was never the app's.
fn copy_tree(from: &Path, to: &Path) -> io::Result<()> {
    fs::create_dir(to)?;
    for entry in fs::read_dir(from)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        let target = to.join(entry.file_name());
        if kind.is_symlink() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "a link in the data folder",
            ));
        } else if kind.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), &target)?;
            File::open(&target)?.sync_all()?;
        }
    }
    Ok(())
}

/// Whether `a` and `b` hold the same names, kinds and bytes.
pub fn same_tree(a: &Path, b: &Path) -> io::Result<bool> {
    let list = |dir: &Path| -> io::Result<Vec<(std::ffi::OsString, bool)>> {
        let mut names = fs::read_dir(dir)?
            .map(|e| {
                let e = e?;
                Ok((e.file_name(), e.file_type()?.is_dir()))
            })
            .collect::<io::Result<Vec<_>>>()?;
        names.retain(|(name, _)| name != VERIFIED);
        names.sort();
        Ok(names)
    };
    let (left, right) = (list(a)?, list(b)?);
    if left != right {
        return Ok(false);
    }
    for (name, directory) in left {
        let same = if directory {
            same_tree(&a.join(&name), &b.join(&name))?
        } else {
            digest(&a.join(&name))? == digest(&b.join(&name))?
        };
        if !same {
            return Ok(false);
        }
    }
    Ok(true)
}

fn digest(path: &Path) -> io::Result<(u64, Vec<u8>)> {
    let mut input = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0u8; 1024 * 1024];
    let mut size = 0u64;
    loop {
        let count = input.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        size += count as u64;
        hash.update(&buffer[..count]);
    }
    Ok((size, hash.finalize().to_vec()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn scratch(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "jana-data-home-{name}-{}-{nanos}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    /// A roaming folder as builds before this one left it: the core's data and the shell's pid files.
    fn roaming_folder(root: &Path) -> PathBuf {
        let roaming = root.join("Roaming/app.jana.desktop");
        fs::create_dir_all(roaming.join("core/profiles/p1")).unwrap();
        fs::write(
            roaming.join("core/profiles/p1/learner.db"),
            b"synthetic learner rows",
        )
        .unwrap();
        fs::write(roaming.join("shell-pids.json"), b"[]").unwrap();
        roaming
    }

    fn holds_the_data(local: &Path) {
        assert_eq!(
            fs::read(local.join("core/profiles/p1/learner.db")).unwrap(),
            b"synthetic learner rows"
        );
        assert_eq!(fs::read(local.join("shell-pids.json")).unwrap(), b"[]");
    }

    #[test]
    fn test_dat01_roaming_data_moves_to_local_once() {
        let root = scratch("move");
        let roaming = roaming_folder(&root);
        let local = root.join("Local/app.jana.desktop");
        fs::create_dir_all(local.join("EBWebView")).unwrap(); // the webview's data is already local
        assert_eq!(resolve(Some(&roaming), &local).unwrap(), local);
        holds_the_data(&local);
        assert!(local.join("EBWebView").is_dir() && !roaming.exists() && !staging(&local).exists());
        assert_eq!(
            migrate(&roaming, &local).unwrap(),
            Moved::Nothing,
            "the next start finds nothing to move"
        );
        assert_eq!(
            resolve(Some(&local), &local).unwrap(),
            local,
            "macOS and Linux: one folder"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn test_dat01_cross_volume_copy_verifies_before_deleting() {
        let root = scratch("copy");
        let roaming = roaming_folder(&root);
        let local = root.join("Local/app.jana.desktop");
        let staged = staging(&local);
        // As if renaming failed: the copy is made and checked against the untouched original.
        fs::create_dir_all(staged.parent().unwrap()).unwrap();
        copy_tree(&roaming, &staged).unwrap();
        assert!(same_tree(&roaming, &staged).unwrap());
        fs::write(staged.join("shell-pids.json"), b"[1]").unwrap();
        assert!(
            !same_tree(&roaming, &staged).unwrap(),
            "a changed byte fails the check"
        );
        fs::remove_dir_all(&staged).unwrap();
        // An interrupted copy (no marker) is thrown away and made again from the original, which is never touched.
        fs::create_dir_all(staged.join("core")).unwrap();
        fs::write(staged.join("core/partial"), b"half a file").unwrap();
        assert_eq!(
            migrate(&roaming, &local).unwrap(),
            Moved::All { copied: false }
        );
        holds_the_data(&local);
        assert!(!local.join("core/partial").exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn test_dat01_interrupted_move_resumes() {
        let root = scratch("resume");
        let roaming = roaming_folder(&root);
        let local = root.join("Local/app.jana.desktop");
        let staged = staging(&local);
        fs::create_dir_all(&local).unwrap();
        // Interrupted after the whole-folder rename and one entry's move, before the marker was written.
        fs::rename(&roaming, &staged).unwrap();
        fs::rename(
            staged.join("shell-pids.json"),
            local.join("shell-pids.json"),
        )
        .unwrap();
        assert_eq!(resolve(Some(&roaming), &local).unwrap(), local);
        holds_the_data(&local);
        assert!(!staged.exists());
        // Interrupted after a verified copy, with the original half deleted: the deletion finishes, the moves resume.
        let roaming = roaming_folder(&root);
        let local = root.join("Local2/app.jana.desktop");
        let staged = staging(&local);
        fs::create_dir_all(staged.parent().unwrap()).unwrap();
        copy_tree(&roaming, &staged).unwrap();
        write_marker(&staged).unwrap();
        fs::remove_file(roaming.join("shell-pids.json")).unwrap();
        assert_eq!(resolve(Some(&roaming), &local).unwrap(), local);
        holds_the_data(&local);
        assert!(!roaming.exists() && !staged.exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn test_dat01_local_entry_is_never_overwritten() {
        let root = scratch("kept");
        let roaming = roaming_folder(&root);
        let local = root.join("Local/app.jana.desktop");
        fs::create_dir_all(local.join("core")).unwrap();
        fs::write(local.join("core/local-only"), b"newer local data").unwrap();
        assert_eq!(
            migrate(&roaming, &local).unwrap(),
            Moved::Kept(vec!["core".into()])
        );
        assert_eq!(
            fs::read(local.join("core/local-only")).unwrap(),
            b"newer local data"
        );
        assert_eq!(
            fs::read(staging(&local).join("core/profiles/p1/learner.db")).unwrap(),
            b"synthetic learner rows",
            "the roaming copy is kept, not deleted"
        );
        assert_eq!(fs::read(local.join("shell-pids.json")).unwrap(), b"[]");
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn test_dat01_failed_copy_keeps_using_roaming() {
        let root = scratch("refused");
        let roaming = roaming_folder(&root);
        std::os::unix::fs::symlink("/etc/hosts", roaming.join("link")).unwrap();
        let local = root.join("Local/app.jana.desktop");
        // Renaming works here, so stage a copy by hand to exercise the cross-volume refusal.
        assert!(copy_tree(&roaming, &staging(&local)).is_err());
        let _ = fs::remove_dir_all(staging(&local));
        // A local folder on a volume that cannot be created: the move fails before anything leaves roaming.
        let blocked = root.join("blocked");
        fs::write(&blocked, b"a file, not a folder").unwrap();
        let unreachable = blocked.join("app.jana.desktop");
        assert_eq!(resolve(Some(&roaming), &unreachable).unwrap(), roaming);
        assert!(roaming.join("core/profiles/p1/learner.db").is_file());
        fs::remove_dir_all(root).unwrap();
    }
}
