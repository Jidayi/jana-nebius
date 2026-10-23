//! Internal authoring shell. No student runtime, generic filesystem command, HTTP server or shell execution.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod bridge;
use bridge::Bridge;
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};
use tauri::{Manager, WindowEvent};
use tauri_plugin_dialog::DialogExt;

#[derive(Default)]
struct Workspace(Mutex<Option<Arc<Bridge>>>);

#[tauri::command]
async fn studio_open(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let choice = app.dialog().file().blocking_pick_folder();
        let Some(choice) = choice else {
            return Ok(None);
        };
        let root = choice.into_path().map_err(|e| e.to_string())?;
        let bridge = Arc::new(Bridge::open(
            &root,
            &app.path().resource_dir().map_err(|e| e.to_string())?,
        )?);
        let inventory = bridge.request(json!({"op": "workspace"}))?;
        if inventory.get("error").is_none() {
            let workspace = app.state::<Workspace>();
            let mut state = workspace
                .0
                .lock()
                .map_err(|_| "Workspace state is unavailable.")?;
            if let Some(old) = state.take() {
                old.stop();
            }
            *state = Some(bridge);
        }
        Ok(Some(inventory))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn studio_command(app: tauri::AppHandle, request: Value) -> Result<Value, String> {
    let bridge = app
        .state::<Workspace>()
        .0
        .lock()
        .map_err(|_| "Workspace state is unavailable.")?
        .clone()
        .ok_or("Open a workspace first.")?;
    tauri::async_runtime::spawn_blocking(move || bridge.request(request))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
fn studio_exit(app: tauri::AppHandle) {
    if let Ok(state) = app.state::<Workspace>().0.lock()
        && let Some(bridge) = state.as_ref()
    {
        bridge.stop();
    }
    app.exit(0);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Workspace::default())
        .invoke_handler(tauri::generate_handler![
            studio_open,
            studio_command,
            studio_exit
        ])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                if let Some(view) = window.app_handle().get_webview_window("main") {
                    let _ = view.eval("window.dispatchEvent(new Event('studio-close-request'))");
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("studio desktop application starts");
}
