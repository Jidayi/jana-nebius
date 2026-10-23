// Synthetic browser heap probe. Uses the shipping runtime/cache teardown with a core served outside the webview.
import { useEffect, useMemo, useState } from "react";
import { SessionController } from "@jana/client-core";
import { LocaleProvider, RegistryProvider, StoreProvider, TutorScreen, defaultRegistry } from "@jana/ui";
import { createRuntime } from "../src/App.js";

export function ProfileIsolation() {
  const runtime = useMemo(() => createRuntime({ endpoint: async () => ({ baseUrl: "http://core.test", token: "launch-token" }) }), []);
  const [profiles, setProfiles] = useState<{ profile_id: string; display_name: string }[]>([]);
  const [session, setSession] = useState<SessionController | null>(null);
  const [ready, setReady] = useState(false);
  const registry = useMemo(defaultRegistry, []);
  useEffect(() => { void runtime.profiles.load().then(() => setProfiles(runtime.profiles.getView().profiles)); }, [runtime]);
  useEffect(() => runtime.profiles.onClear(() => { setSession((old) => { old?.close(); return null; }); setReady(false); }), [runtime]);
  const open = async (profileId: string) => {
    setReady(false); await runtime.profiles.unlock(profileId);
    const listed = await runtime.profiles.commands.get<{ sessions: { session_id: string }[] }>("/v1/sessions");
    const target = listed.sessions[0]; if (!target) throw new Error("Synthetic profile has no session");
    const current = new SessionController(runtime.profiles.launch, runtime.holder, target.session_id);
    setSession(current); await current.open(); setReady(true);
  };
  return <LocaleProvider locale="en"><div data-isolation-ready={ready ? "yes" : "no"}>
    {profiles.map((p) => <button key={p.profile_id} onClick={() => void open(p.profile_id)}>{p.display_name}</button>)}
    {session && <RegistryProvider key={session.sessionId} registry={registry}><StoreProvider holder={runtime.holder} session={session}><TutorScreen sessionId={session.sessionId} /></StoreProvider></RegistryProvider>}
  </div></LocaleProvider>;
}
