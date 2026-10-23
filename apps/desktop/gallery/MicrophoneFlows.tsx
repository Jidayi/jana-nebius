// Synthetic audio/socket/core boundaries around the shipping composer and controllers. Development gallery only.
import { useEffect, useMemo } from "react";
import { CommandClient, SpeechController, StoreHolder, VoiceController, emptyStore, hydrate, typedCapture, type CoreSnapshot, type SessionController, type VoiceSocket } from "@jana/client-core";
import { Composer, LocaleProvider, SpeechToolsProvider, StoreProvider } from "@jana/ui";
import { VoiceBar } from "../src/VoiceBar.js";
class Socket implements VoiceSocket {
  binaryType: BinaryType = "arraybuffer"; readyState = 0; bufferedAmount = 0;
  onopen: (() => void) | null = null; onclose: (() => void) | null = null; onerror: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  send() { /* The synthetic core emits only the selected error. */ }
  close() { this.readyState = 3; this.onclose?.(); }
}
export function MicrophoneFlows() {
  const params = new URLSearchParams(location.search), reason = params.get("reason") ?? "voice.too_noisy";
  const runtime = useMemo(() => {
    const sessionId = `ses_${"0".repeat(26)}`, holder = new StoreHolder(), sent: unknown[] = [];
    holder.update(() => hydrate(emptyStore(), { session: { session_id: sessionId, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false }, cursor: { epoch: "ep_mic_fixture", seq: 0 }, messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null } satisfies CoreSnapshot));
    let released = 0;
    const voice = new VoiceController(sessionId, async () => ({ baseUrl: "http://127.0.0.1", token: "synthetic" }), {
      capture: async () => ({ echoCancellation: true, headphones: false }), releaseMic: () => { released++; }, play: () => undefined, flush: () => undefined, close: () => { released++; },
    }, () => { const socket = new Socket(); queueMicrotask(() => { socket.readyState = 1; socket.onopen?.(); }); return socket; });
    const capture = { ...typedCapture("", { sessionId, purpose: "question", confirmed: false }), source: "voice" as const };
    const commands = new CommandClient({ endpoint: async () => ({ baseUrl: "http://127.0.0.1", token: "synthetic" }), fetch: (async (url, init) => init?.method === "DELETE" ? new Response(null, { status: 204 }) : Response.json(new URL(String(url)).pathname.endsWith("/captures") ? { captures: [] } : capture)) as typeof fetch });
    const speech = new SpeechController(sessionId, commands, voice, { available: () => true, subscribe: () => () => undefined, speak: () => () => undefined }, true);
    const session = { commands, sessionId, sendCapture: (record: unknown, intent: string) => { sent.push({ capture: record, intent }); return "cli_synthetic_mic"; }, discardFailed: () => undefined } as unknown as SessionController;
    return { sessionId, holder, voice, speech, session, evidence: () => ({ sent, released, dictation: speech.getState().dictation, error: speech.getState().error }) };
  }, []);
  useEffect(() => { runtime.speech.activate(); Object.defineProperty(globalThis, "__jana_microphone_evidence", { configurable: true, get: runtime.evidence }); return () => { runtime.speech.close(); }; }, [runtime]);
  return <LocaleProvider locale="en"><main data-microphone-flow="" data-theme={params.get("theme") ?? "light"} className="min-h-screen bg-canvas p-6 text-ink"><h1>Microphone recovery</h1>
    <button type="button" onClick={() => runtime.voice.event({ type: "voice.state", state: "unavailable", reason_key: reason })}>Simulate microphone error</button>
    <StoreProvider holder={runtime.holder} session={runtime.session}><SpeechToolsProvider controller={runtime.speech}>
      <VoiceBar controller={runtime.voice} /><Composer sessionId={runtime.sessionId} />
    </SpeechToolsProvider></StoreProvider>
  </main></LocaleProvider>;
}
