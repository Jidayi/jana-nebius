//! A process the shell starts and everything it starts in turn, ended together (ARC-23, ARC-24).
//!
//! On macOS and Linux the process leads its own process group: a polite stop is SIGTERM to the group and a kill is
//! SIGKILL to the group. On Windows there are no process groups to signal, so the process is placed in a job object
//! with kill-on-close: closing the shell's only handle to the job (a kill, or the shell itself ending, even by a
//! crash) ends every process in it; a polite stop is the control channel's own (`control.shutdown`) or none. The
//! child is also killed directly, so a quit never waits on a live process whatever the job holds.

use std::process::{Child, Command};
#[cfg(windows)]
use std::sync::Mutex;

/// Make `command` start its own tree (on Unix, a new process group it leads).
pub fn isolate(command: &mut Command) {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(not(unix))]
    {
        let _ = command; // the job object is joined once the process exists (`Tree::adopt`)
    }
}

/// One started process's tree.
pub struct Tree {
    pid: u32,
    /// The kill-on-close job holding the process and its descendants; dropping it ends them all.
    #[cfg(windows)]
    job: Mutex<Option<win32job::Job>>,
}

impl Tree {
    /// Take charge of a process just started by a command passed through [`isolate`]. On Windows a process it
    /// started before this call is outside the job; the core and the runtime start nothing that early.
    pub fn adopt(child: &Child) -> Tree {
        Tree {
            pid: child.id(),
            #[cfg(windows)]
            job: Mutex::new(job_for(child)),
        }
    }

    pub fn pid(&self) -> u32 {
        self.pid
    }

    /// Ask the tree to stop (Unix: SIGTERM to the group; Windows has no such signal).
    pub fn terminate(&self) {
        #[cfg(unix)]
        signal_group(self.pid, nix::sys::signal::Signal::SIGTERM);
    }

    /// End the whole tree now.
    pub fn kill(&self) {
        #[cfg(unix)]
        signal_group(self.pid, nix::sys::signal::Signal::SIGKILL);
        // Closing the only handle to the kill-on-close job ends every process in it.
        #[cfg(windows)]
        drop(self.job.lock().unwrap_or_else(|p| p.into_inner()).take());
    }
}

/// End a child that this thread owns: the tree first, then the process itself, so `wait` cannot block on it.
pub fn kill_child(tree: &Tree, child: &mut Child) {
    tree.kill();
    if matches!(child.try_wait(), Ok(None)) {
        let _ = child.kill();
    }
}

/// A started process shared between the thread that watches it and a quit that may have to end it.
pub struct Started {
    tree: Tree,
    child: std::sync::Mutex<Child>,
}

impl Started {
    /// Take charge of a process (its pipes already taken) started by a command passed through [`isolate`].
    pub fn new(child: Child) -> Started {
        Started {
            tree: Tree::adopt(&child),
            child: std::sync::Mutex::new(child),
        }
    }

    pub fn pid(&self) -> u32 {
        self.tree.pid()
    }

    /// End the process and its tree now.
    pub fn kill(&self) {
        kill_child(
            &self.tree,
            &mut self.child.lock().unwrap_or_else(|p| p.into_inner()),
        );
    }

    /// Wait for the process to end, without keeping a concurrent [`Started::kill`] from reaching it.
    pub fn wait(&self) {
        loop {
            match self
                .child
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .try_wait()
            {
                Ok(None) => {}
                _ => return,
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    }
}

#[cfg(unix)]
fn signal_group(pid: u32, signal: nix::sys::signal::Signal) {
    let _ = nix::sys::signal::killpg(nix::unistd::Pid::from_raw(pid as i32), signal);
}

#[cfg(windows)]
fn job_for(child: &Child) -> Option<win32job::Job> {
    use std::os::windows::io::AsRawHandle;
    let mut limits = win32job::ExtendedLimitInfo::new();
    limits.limit_kill_on_job_close();
    let job = win32job::Job::create_with_limit_info(&limits).ok()?;
    job.assign_process(child.as_raw_handle() as isize).ok()?;
    Some(job)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    /// A process that does not stop when asked is ended by `kill_child`, and waiting on it then returns at once
    /// (the quit path never blocks on a live runtime).
    #[test]
    fn kill_child_never_leaves_wait_blocked() {
        let mut command = if cfg!(windows) {
            let mut c = Command::new("cmd");
            c.args(["/C", "ping -n 60 127.0.0.1 >NUL"]);
            c
        } else {
            let mut c = Command::new("sh");
            c.args(["-c", "trap '' TERM; sleep 60 & wait"]);
            c
        };
        isolate(&mut command);
        let mut child = command.spawn().unwrap();
        let tree = Tree::adopt(&child);
        assert_eq!(tree.pid(), child.id());
        std::thread::sleep(Duration::from_millis(300)); // the shell has set its trap
        tree.terminate();
        std::thread::sleep(Duration::from_millis(200));
        assert!(
            matches!(child.try_wait(), Ok(None)),
            "it ignores the polite stop"
        );
        let started = Instant::now();
        kill_child(&tree, &mut child);
        child.wait().unwrap();
        assert!(started.elapsed() < Duration::from_secs(5));
    }
}
