// Where the core is and the per-launch token (API-02). The webview gets both from the shell through a Tauri command
// and keeps the token in memory only; in development the Vite dev server provides them.
export interface LaunchInfo {
  base_url: string;
  token: string;
}

interface TauriInternals {
  invoke(cmd: string, args?: Record<string, unknown>): Promise<unknown>;
}

export async function pickInstallSource(kind: "folder" | "pack" | "update"): Promise<string | null> {
  const tauri = (globalThis as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  if (tauri === undefined) return null;
  return (await tauri.invoke("pick_install_source", { kind })) as string | null;
}

/** Profile archives use a native file picker with their own fixed filter and command capability. */
export async function pickProfileArchive(): Promise<string | null> {
  const tauri = (globalThis as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  return tauri === undefined ? null : await tauri.invoke("pick_profile_archive") as string | null;
}

export async function updateRecovery(): Promise<string | null> {
  const tauri = (globalThis as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  return tauri === undefined ? null : (await tauri.invoke("update_recovery")) as string | null;
}

export async function rollbackUpdate(): Promise<void> {
  const tauri = (globalThis as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  if (tauri !== undefined) await tauri.invoke("rollback_update");
}

export async function launchInfo(refresh = false): Promise<LaunchInfo> {
  const tauri = (globalThis as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  if (tauri !== undefined) return (await tauri.invoke("launch_info", { refresh })) as LaunchInfo;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);
  try {
    for (let attempt = 0; ; attempt += 1) {
      if (controller.signal.aborted) throw new Error("The local tutor did not start in time");
      const response = await fetch("/__jana_dev/launch", { cache: "no-store", signal: controller.signal });
      if (response.ok) return (await response.json()) as LaunchInfo;
      // A starting host may recover; a failed host must reach the app's retry screen.
      if (response.status !== 503) throw new Error("The local tutor could not start");
      await new Promise((r) => setTimeout(r, Math.min(2000, 200 * (attempt + 1))));
    }
  } finally { clearTimeout(timeout); }
}
