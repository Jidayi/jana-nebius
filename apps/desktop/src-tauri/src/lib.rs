//! The desktop shell (ARC-02): starts and supervises the agent core and the model runtime, hands the webview its
//! launch info, and quits without leaving processes behind. The Tauri entry point is `main.rs`; everything here runs without a window, so
//! it is tested headless.
pub mod control;
pub mod data_home;
pub mod generated;
pub mod keychain;
pub mod launch;
pub mod orphans;
pub mod process_tree;
pub mod runtime;
pub mod supervisor;
pub mod variants;
pub mod voice;
pub mod voice_sandbox;

pub mod net;

// M20: packaging, downloads, updates and crash capture.
pub mod crash;
pub mod download_http;
pub mod download_runner;
pub mod downloads;
pub mod installer;
pub mod update_install;
pub mod updates;
