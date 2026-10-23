//! The Tauri entry point: one window, the commands the UI invokes (each declared in `build.rs` and granted in the
//! capability file, SEC-11), the core and the model runtime supervised for the life of the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use jana_shell::control::{Config, ToShell};
use jana_shell::generated::keys;
use jana_shell::keychain::KeyStore;
use jana_shell::runtime::{Builds, CoreLink, RuntimeCommand, RuntimePolicy, RuntimeSupervisor};
use jana_shell::supervisor::{CoreCommand, LaunchInfo, Policy, Supervisor};
use jana_shell::variants;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent};
use tauri_plugin_dialog::DialogExt;

struct Core(Arc<Supervisor>);
struct Runtime(Arc<RuntimeSupervisor>);
struct Downloads(jana_shell::download_runner::Runner);
struct UpdateExit(Arc<AtomicBool>);
struct Recovery(CoreCommand, PathBuf);
/// The data folder this run resolved (`data_home`), for the update hand-off at exit.
struct DataHome(PathBuf);

#[tauri::command]
async fn update_recovery(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let data = app.state::<Recovery>().1.clone();
    let failed = matches!(
        app.state::<Core>().0.state(),
        jana_shell::supervisor::State::GaveUp | jana_shell::supervisor::State::Incompatible
    );
    tauri::async_runtime::spawn_blocking(move || {
        let path = data.join("updates/update-state.json");
        if !path.is_file() {
            return Ok(None);
        }
        let bytes = std::fs::read(path).map_err(|_| "recovery_unavailable".to_string())?;
        let state: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| "recovery_unavailable".to_string())?;
        if state["phase"] != "rollback_offered" && !(failed && state["phase"] == "installing") {
            return Ok(None);
        }
        Ok(state["previous"]["version"].as_str().map(String::from))
    })
    .await
    .map_err(|_| "recovery_unavailable".to_string())?
}

#[tauri::command]
async fn rollback_update(app: tauri::AppHandle) -> Result<(), String> {
    if update_recovery(app.clone()).await?.is_none() {
        return Err("recovery_unavailable".into());
    }
    let app_for_work = app.clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        let app = app_for_work;
        let recovery = app.state::<Recovery>();
        let data = recovery.1.clone();
        app.state::<Downloads>().0.shutdown();
        app.state::<Core>().0.shutdown();
        if let Some(runtime) = app.try_state::<Runtime>() {
            runtime
                .0
                .shutdown(Duration::from_secs_f64(keys::SHUTDOWN_TOTAL_S));
        }
        let mut command = std::process::Command::new(&recovery.0.program);
        command
            .args(&recovery.0.args)
            .args(["--update-recovery", "rollback", "--data-dir"])
            .arg(&data)
            .current_dir(&recovery.0.cwd);
        if recovery.0.config.release {
            command.arg("--release");
        }
        let result = command
            .stdin(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .output()
            .map_err(|_| "recovery_unavailable".to_string())?;
        if !result.status.success() {
            return Err("recovery_unavailable".into());
        }
        let frame: ToShell = serde_json::from_slice(&result.stdout)
            .map_err(|_| "recovery_unavailable".to_string())?;
        let ToShell::UpdateInstall(plan) = frame else {
            return Err("recovery_unavailable".into());
        };
        jana_shell::update_install::launch(&data, &plan)
            .map_err(|_| "recovery_unavailable".to_string())?;
        Ok(())
    })
    .await
    .map_err(|_| "recovery_unavailable".to_string())??;
    app.exit(0);
    Ok(())
}

#[tauri::command]
async fn pick_install_source(
    app: tauri::AppHandle,
    kind: String,
) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let picker = app.dialog().file();
        let choice = match kind.as_str() {
            "folder" => picker.blocking_pick_folder(),
            "update" => picker
                .add_filter("Jana update", &["janaupdate"])
                .blocking_pick_file(),
            "pack" => picker
                .add_filter("Jana content", &["janapack", "pack", "db"])
                .blocking_pick_file(),
            _ => return Err("invalid_request".into()),
        };
        choice
            .map(|file| {
                file.into_path()
                    .map(|p| p.to_string_lossy().into_owned())
                    .map_err(|_| "invalid_request".to_string())
            })
            .transpose()
    })
    .await
    .map_err(|_| "internal_error".to_string())?
}

#[tauri::command]
async fn pick_profile_archive(app: tauri::AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .add_filter("Jana profile", &["janaprofile"])
            .blocking_pick_file()
            .map(|file| {
                file.into_path()
                    .map(|path| path.to_string_lossy().into_owned())
                    .map_err(|_| "invalid_request".to_string())
            })
            .transpose()
    })
    .await
    .map_err(|_| "internal_error".to_string())?
}

/// Development builds may point at a local llama-server (for example Homebrew's) with this variable; without it they
/// run the scripted provider and start no runtime.
const DEV_RUNTIME_VAR: &str = "JANA_LLAMA_SERVER";
/// Development builds may name a signed pilot-country file with this variable to run as a pilot build (PRD-22).
const DEV_PILOT_COUNTRY_VAR: &str = "JANA_PILOT_COUNTRY_FILE";

/// The core's device secrets (SEC-17, D97): the OS keychain under the app's identifier, or the file fallback in the
/// user's configuration folder, outside the app data folder (`$XDG_CONFIG_HOME/jana/keys` on Linux; on Windows the
/// local `%LOCALAPPDATA%\jana\keys`, never the roaming folder, where builds before this one kept it and from which it
/// is moved). Development builds keep theirs apart from an installed app's.
fn key_store(app: &tauri::App, data_dir: &std::path::Path) -> std::io::Result<KeyStore> {
    let (service, folder) =
        jana_shell::keychain::service_and_folder(&app.config().identifier, cfg!(debug_assertions));
    let roaming = app
        .path()
        .config_dir()
        .ok()
        .map(|c| c.join("jana").join(folder));
    let fallback = if cfg!(windows) {
        let local = app
            .path()
            .local_data_dir()
            .map_err(std::io::Error::other)?
            .join("jana")
            .join(folder);
        jana_shell::data_home::resolve(roaming.as_deref(), &local)?
    } else {
        roaming.unwrap_or_default()
    };
    Ok(KeyStore::open(&service, fallback, data_dir))
}

/// The app's data folder (DAT-01): the local application data folder, after moving what builds before this one kept
/// in the roaming folder (Windows; on macOS and Linux they are one folder). See `data_home`.
fn data_home(app: &tauri::App) -> std::io::Result<PathBuf> {
    let local = app
        .path()
        .app_local_data_dir()
        .map_err(std::io::Error::other)?;
    let roaming = app.path().app_data_dir().ok();
    jana_shell::data_home::resolve(roaming.as_deref(), &local)
}

/// The core's address and per-launch token for the webview, kept in its memory only (API-02). After a core restart
/// the webview asks again (`refresh`) and gets the new process's address and token. It waits for a starting core off
/// the main thread, so the window keeps painting meanwhile.
#[tauri::command]
async fn launch_info(app: tauri::AppHandle, refresh: bool) -> Result<LaunchInfo, String> {
    let _ = refresh;
    let core = app
        .try_state::<Core>()
        .ok_or_else(|| "core_unavailable".to_string())?
        .0
        .clone();
    tauri::async_runtime::spawn_blocking(move || core.launch_info(Duration::from_secs(60)))
        .await
        .ok()
        .flatten()
        .ok_or_else(|| "core_unavailable".to_string())
}

/// The runtime builds: in a release the bundled llama.cpp builds this machine may run, best first (PLT-04, chosen on
/// the supervisor's thread); in development only the one program `JANA_LLAMA_SERVER` names.
fn runtime_builds(app: &tauri::App) -> Option<Box<dyn FnOnce() -> Builds + Send>> {
    if cfg!(debug_assertions) {
        let program = PathBuf::from(std::env::var_os(DEV_RUNTIME_VAR)?);
        return Some(Box::new(move || {
            Builds::single(RuntimeCommand {
                program,
                prefix_args: vec![],
            })
        }));
    }
    let resources = app.path().resource_dir().unwrap_or_default();
    Some(Box::new(move || {
        variants::select(&resources, variants::this_cpu(), &[])
    }))
}

/// How to start the agent core: the bundled one-dir sidecar in a release, `uv run` from the repository in development.
fn core_command(
    app: &tauri::App,
    data_dir: PathBuf,
    scripted: bool,
    keys: KeyStore,
) -> CoreCommand {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let release = !cfg!(debug_assertions);
    let pilot_country_file = if release {
        jana_shell::supervisor::pilot_country_file(&app.path().resource_dir().unwrap_or_default())
    } else {
        std::env::var(DEV_PILOT_COUNTRY_VAR)
            .ok()
            .filter(|path| !path.is_empty())
    };
    let (program, args, cwd, content, skills) = if release {
        let resources = app.path().resource_dir().unwrap_or_default();
        (
            resources.join("agent-core/agent-core"),
            vec![],
            resources.clone(),
            resources.join("content/agent"),
            resources.join("skills"),
        )
    } else {
        (
            PathBuf::from("uv"),
            ["run", "--quiet", "python", "-m", "agent_core.api"]
                .map(String::from)
                .to_vec(),
            repo.clone(),
            repo.join("content/agent"),
            repo.join("skills"),
        )
    };
    CoreCommand {
        program,
        args,
        cwd,
        config: Config {
            data_dir: data_dir.display().to_string(),
            content_root: content.display().to_string(),
            skills_root: skills.display().to_string(),
            release,
            dev_origins: (!release).then(|| vec!["http://localhost:5180".into()]),
            scripted: (!release && scripted).then_some(true),
            pilot_country_file,
        },
        keys: Arc::new(keys),
        net_hint: jana_shell::net::os_route_hint,
    }
}

fn main() {
    let context = tauri::generate_context!();
    // PLT-24, G81: the uninstaller's delete choice runs `--uninstall-keys` to remove the app's keychain items and
    // fallback key files, with no window and no core.
    let args: Vec<String> = std::env::args().collect();
    if let Some(request) = jana_shell::keychain::uninstall_keys_args(&args) {
        std::process::exit(jana_shell::keychain::uninstall_keys_main(
            &context.config().identifier,
            cfg!(debug_assertions),
            &request,
        ));
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            launch_info,
            pick_install_source,
            pick_profile_archive,
            update_recovery,
            rollback_update
        ])
        .setup(|app| {
            let data_dir = data_home(app)?;
            std::fs::create_dir_all(&data_dir)?;
            let runtime = runtime_builds(app);
            let core_data = data_dir.join("core");
            // OBS-16: a shell panic leaves a crash record the core takes in at its next start.
            jana_shell::crash::install_panic_hook(
                core_data.join("crashes"),
                env!("CARGO_PKG_VERSION"),
            );
            let keys = key_store(app, &data_dir)?;
            let command = core_command(app, core_data.clone(), runtime.is_none(), keys);
            app.manage(Recovery(command.clone(), core_data.clone()));
            app.manage(DataHome(data_dir.clone()));
            let release = command.config.release;
            let core = Arc::new(Supervisor::start(
                command,
                Policy::default(),
                Some(data_dir.join("shell-pids.json")),
            ));
            let update_stop = Arc::new(AtomicBool::new(false));
            app.manage(UpdateExit(update_stop.clone()));
            let watched = core.clone();
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                while !update_stop.load(Ordering::SeqCst) {
                    if watched.take_exit_requested() {
                        handle.exit(0);
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
            });
            app.manage(Downloads(jana_shell::download_runner::Runner::start(
                core.clone(),
                core_data.clone(),
                release,
            )));
            if let Some(runtime) = runtime {
                let link: Arc<dyn CoreLink> = core.clone();
                let supervisor = RuntimeSupervisor::start_builds(
                    link,
                    core_data.join("runtime").join("launch.json"),
                    runtime,
                    RuntimePolicy::default(),
                    Some(data_dir.join("runtime-pids.json")),
                );
                app.manage(Runtime(Arc::new(supervisor)));
            }
            app.manage(Core(core));
            Ok(())
        })
        .build(context)
        .expect("the Tauri application builds");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<UpdateExit>().0.store(true, Ordering::SeqCst);
            // ARC-23: the core first (it ends its turns and the worker), then the runtime, inside the total deadline.
            let started = Instant::now();
            if let Some(downloads) = handle.try_state::<Downloads>() {
                downloads.0.shutdown();
            }
            handle.state::<Core>().0.shutdown();
            if let Some(runtime) = handle.try_state::<Runtime>() {
                let total = Duration::from_secs_f64(keys::SHUTDOWN_TOTAL_S);
                runtime.0.shutdown(total.saturating_sub(started.elapsed()));
            }
            if let Some(plan) = handle.state::<Core>().0.take_update_install() {
                let data = handle.state::<DataHome>().0.join("core");
                if jana_shell::update_install::launch(&data, &plan).is_err() {
                    jana_shell::update_install::record_failure(&data);
                }
            }
        }
    });
}
