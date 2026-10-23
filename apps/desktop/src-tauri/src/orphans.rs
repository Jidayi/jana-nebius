//! Orphans from a previous run (ARC-24): the shell records each process it starts (the agent core and the model
//! runtime, each in its own file) with its PID, executable and start time, and at the next start kills only processes
//! that match all three, never by name, so a PID reused by an unrelated process is left alone.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use sysinfo::{Pid, ProcessRefreshKind, ProcessesToUpdate, System, UpdateKind};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Record {
    pub pid: u32,
    pub start_time: u64,
    pub exe: String,
}

fn system_for(pid: u32) -> System {
    let mut system = System::new();
    system.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[Pid::from_u32(pid)]),
        true,
        ProcessRefreshKind::nothing().with_exe(UpdateKind::Always),
    );
    system
}

/// The identity of a running process, if it runs.
pub fn identify(pid: u32) -> Option<Record> {
    let system = system_for(pid);
    let process = system.process(Pid::from_u32(pid))?;
    Some(Record {
        pid,
        start_time: process.start_time(),
        exe: process
            .exe()
            .map(|p| p.display().to_string())
            .unwrap_or_default(),
    })
}

/// Record the process just started as the one this file tracks.
pub fn track(path: &Path, pid: u32) {
    if let Some(record) = identify(pid) {
        let _ = save(path, &[record]);
    }
}

pub fn save(path: &Path, records: &[Record]) -> std::io::Result<()> {
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, serde_json::to_vec(records).unwrap_or_default())?;
    fs::rename(tmp, path)
}

pub fn load(path: &Path) -> Vec<Record> {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

/// Kill the recorded processes that are still the same processes. Returns the PIDs killed.
pub fn recover(path: &Path) -> Vec<u32> {
    let mut killed = Vec::new();
    for record in load(path) {
        if identify(record.pid).as_ref() == Some(&record) {
            let system = system_for(record.pid);
            if let Some(process) = system.process(Pid::from_u32(record.pid))
                && process.kill()
            {
                killed.push(record.pid);
            }
        }
    }
    let _ = fs::remove_file(path);
    killed
}
