// The desktop client entry: the shell gives the core's address and launch token (API-02); the app starts at the
// profile picker (UXS-09). Screens and navigation beyond the tutor and Settings arrive in M18.
import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Launch } from "@jana/client-core";
import "./app.css";
import { LaunchScreen } from "@jana/ui/launch";
import { launchInfo, pickInstallSource, pickProfileArchive, rollbackUpdate, updateRecovery } from "./launch.js";

let info: Promise<{ base_url: string; token: string }> | null = null;
const launch: Launch = {
  endpoint: async (refresh) => {
    if (refresh || info === null) info = launchInfo(refresh);
    const current = await info;
    return { baseUrl: current.base_url, token: current.token };
  },
};
const container = document.getElementById("root") as (HTMLElement & { __jana_root?: Root }) | null;
if (container === null) throw new Error("index.html has no #root");
// One root per page: a development module reload re-renders into it rather than mounting a second one.
container.__jana_root ??= createRoot(container);
const root = container.__jana_root;
// The launch screen fills the window while the app loads, as it does once the app is up (DSN-25).
const launching = (failed: boolean) => <div className="flex h-screen"><LaunchScreen failed={failed} onRetry={() => window.location.reload()} /></div>;
root.render(launching(false));
void import("./App.js").then(({ App, createRuntime }) => {
  const runtime = createRuntime(launch);
  runtime.chooseSource = pickInstallSource;
  runtime.chooseArchive = pickProfileArchive;
  runtime.updateRecovery = updateRecovery;
  runtime.rollbackUpdate = rollbackUpdate;
  root.render(<StrictMode><App runtime={runtime} /></StrictMode>);
}).catch(() => root.render(launching(true)));
