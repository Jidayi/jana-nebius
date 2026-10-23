fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["studio_open", "studio_command", "studio_exit"]),
    ))
    .expect("studio configuration is valid");
}
