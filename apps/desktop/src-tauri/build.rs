fn main() {
    // Every command the webview invokes is declared here and granted in `capabilities/default.json`: with an app
    // manifest, Tauri's ACL rejects any app command that is not both declared and granted (SEC-11).
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "launch_info",
            "pick_install_source",
            "pick_profile_archive",
            "update_recovery",
            "rollback_update",
        ]),
    ))
    .expect("tauri build configuration is valid");
}
