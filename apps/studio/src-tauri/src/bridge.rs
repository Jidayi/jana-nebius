//! Bounded JSON-lines IPC with a supervised authoring process; workspace paths come only from the native picker.
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Mutex, mpsc};
use std::time::Duration;

const INPUT_LIMIT: usize = 512 * 1024;
const OUTPUT_LIMIT: u64 = 4 * 1024 * 1024;
struct Channel {
    input: ChildStdin,
    replies: mpsc::Receiver<Result<Value, String>>,
}
pub struct Bridge {
    child: Mutex<Child>,
    channel: Mutex<Channel>,
}

impl Bridge {
    pub fn open(root: &Path, resources: &Path) -> Result<Self, String> {
        let mut command;
        if let Some(binary) = std::env::var_os("JANA_STUDIO_BACKEND") {
            command = Command::new(binary);
        } else if cfg!(debug_assertions) {
            let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
            let python = std::env::var_os("JANA_STUDIO_PYTHON")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| {
                    repo.join(if cfg!(windows) {
                        ".venv/Scripts/python.exe"
                    } else {
                        ".venv/bin/python"
                    })
                });
            command = Command::new(python);
            command.args(["-m", "pack_builder.studio"]);
        } else {
            command = Command::new(resources.join("studio-backend").join(if cfg!(windows) {
                "studio-backend.exe"
            } else {
                "studio-backend"
            }));
        }
        let mut child = command
            .arg("--workspace")
            .arg(root)
            .arg("--stdio")
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| {
                "The authoring backend is unavailable. Install the internal authoring runtime."
                    .to_string()
            })?;
        let input = child
            .stdin
            .take()
            .ok_or("Authoring input is unavailable.")?;
        let output = child
            .stdout
            .take()
            .ok_or("Authoring output is unavailable.")?;
        let (sender, replies) = mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(output);
            loop {
                let mut line = String::new();
                let read = Read::by_ref(&mut reader)
                    .take(OUTPUT_LIMIT + 1)
                    .read_line(&mut line);
                let result = match read {
                    Ok(0) | Err(_) => Err("The authoring backend stopped.".to_string()),
                    Ok(n) if n as u64 > OUTPUT_LIMIT || !line.ends_with('\n') => {
                        Err("The authoring reply is too large.".to_string())
                    }
                    Ok(_) => serde_json::from_str(&line)
                        .map_err(|_| "The authoring reply is invalid.".to_string()),
                };
                let terminal = result.is_err();
                if sender.send(result).is_err() || terminal {
                    break;
                }
            }
        });
        Ok(Self {
            child: Mutex::new(child),
            channel: Mutex::new(Channel { input, replies }),
        })
    }
    pub fn request(&self, request: Value) -> Result<Value, String> {
        let data = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
        if data.len() > INPUT_LIMIT {
            return Err("The authoring request is too large.".into());
        }
        let mut channel = self
            .channel
            .lock()
            .map_err(|_| "The authoring channel is unavailable.")?;
        channel
            .input
            .write_all(&data)
            .and_then(|()| channel.input.write_all(b"\n"))
            .and_then(|()| channel.input.flush())
            .map_err(|_| "The authoring backend stopped.")?;
        match channel.replies.recv_timeout(Duration::from_secs(60)) {
            Ok(value) => value,
            Err(_) => {
                self.stop();
                Err("Authoring timed out. Your unsaved draft remains in the editor.".into())
            }
        }
    }
    pub fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}
impl Drop for Bridge {
    fn drop(&mut self) {
        self.stop();
    }
}
