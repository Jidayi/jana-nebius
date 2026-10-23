// The component gallery, browsable in development builds only (DSN-16): every state from data, filterable by
// component, with theme, locale and text-scale overrides. Not part of the production build (index.html only).
import { StrictMode, useMemo, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { RENDERERS } from "@jana/renderers";
import { defaultRegistry } from "@jana/ui";
import { DECLARED, GalleryView, STATES } from "@jana/ui/gallery";
import "../src/app.css";
import { MicrophoneFlows } from "./MicrophoneFlows.js";
import { InputFlows } from "./InputFlows.js";
import { KeyboardFlows } from "./KeyboardFlows.js";
import { ProfileIsolation } from "./ProfileIsolation.js";
import { TranscriptBenchmark } from "./TranscriptBenchmark.js";
import { registerVisuals } from "../src/visuals.js";

const registry = registerVisuals(defaultRegistry(), RENDERERS);

function Gallery() {
  const params = new URLSearchParams(window.location.search);
  const [component, setComponent] = useState(params.get("component") ?? "all");
  const theme = params.get("theme");
  const locale = params.get("locale");
  const scale = params.get("scale");
  const stateId = params.get("state");
  const shown = useMemo(() => STATES.filter((s) => (component === "all" || s.component === component) && (stateId === null || s.id === stateId)), [component, stateId]);
  return (
    <div className="min-h-screen bg-chrome p-4 text-ink">
      <select aria-label="component" value={component} onChange={(e) => setComponent(e.target.value)} className="mb-4 rounded-control border border-line-strong bg-canvas px-2 text-ui">
        {["all", ...Object.keys(DECLARED)].map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <div className={stateId === null ? "grid grid-cols-1 gap-4 lg:grid-cols-2" : "grid grid-cols-1 gap-4"}>
        {shown.map((state) => {
          const context = { ...state.context, ...(theme ? { theme } : {}), ...(locale ? { locale } : {}), ...(scale ? { textScale: Number(scale) } : {}) };
          return (
            <section key={state.id} className="rounded-card border border-line bg-canvas">
              <p className="border-b border-line px-3 py-1 font-mono text-meta text-muted">{state.id}</p>
              <GalleryView state={{ ...state, context }} registry={registry} />
            </section>
          );
        })}
      </div>
    </div>
  );
}

const container = document.getElementById("root") as (HTMLElement & { __jana_root?: Root }) | null;
if (container === null) throw new Error("gallery.html has no #root");
// One root per page: a development module reload re-renders into it rather than mounting a second one.
container.__jana_root ??= createRoot(container);
container.__jana_root.render(
  <StrictMode>
    {new URLSearchParams(window.location.search).get("benchmark") === "microphone-flows" ? <MicrophoneFlows /> : new URLSearchParams(window.location.search).get("benchmark") === "input-flows" ? <InputFlows /> : new URLSearchParams(window.location.search).get("benchmark") === "transcript" ? <TranscriptBenchmark /> : new URLSearchParams(window.location.search).get("benchmark") === "profile-isolation" ? <ProfileIsolation /> : new URLSearchParams(window.location.search).get("benchmark") === "keyboard-flows" ? <KeyboardFlows /> : <Gallery />}
  </StrictMode>,
);
