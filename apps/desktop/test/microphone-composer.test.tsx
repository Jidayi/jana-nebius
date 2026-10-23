// Actual speech/voice controllers, rich Composer and voice bar; audio, sockets and core IO are scripted boundaries.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CommandClient, MICROPHONE_REASONS, SpeechController, VoiceController, typedCapture, type SessionController, type VoiceAudio, type VoiceSocket } from "@jana/client-core";
import { Composer, LocaleProvider, SpeechToolsProvider, StoreProvider } from "@jana/ui";
import { STATES } from "@jana/ui/gallery";
import { VoiceBar } from "../src/VoiceBar.js";
import { Fixture, SESSION } from "../../../packages/ui/test/harness.js";
class Socket implements VoiceSocket {
  binaryType: BinaryType = "arraybuffer"; readyState = 0; bufferedAmount = 0;
  onopen: (() => void) | null = null; onclose: (() => void) | null = null; onerror: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  send = vi.fn((_data: string | ArrayBuffer) => undefined); close() { this.readyState = 3; this.onclose?.(); }
}
const copies: Record<string, string> = {
  "voice.microphone_missing": "No microphone found. Plug one in or keep typing.",
  "voice.microphone_denied": "Microphone access is off for this app. Open system settings to allow it.",
  "voice.microphone_unavailable": "The microphone is unavailable. Check its permission or keep typing.",
  "voice.too_noisy": "It's noisy here. Try Hold Space to talk, or hold the mic close and speak clearly.",
};
const controllers: SpeechController[] = [];
afterEach(() => { cleanup(); for (const controller of controllers.splice(0)) controller.close(); });
function paste(editor: HTMLElement, text: string) { fireEvent.paste(editor, { clipboardData: { files: [], types: ["text/plain"], getData: (kind: string) => kind === "text/plain" ? text : "" } }); }
function setup(theme: string, pending: boolean) {
  let onPcm: (pcm: ArrayBuffer) => void = () => undefined; const sockets: Socket[] = [];
  const audio: VoiceAudio = { activate: vi.fn(), capture: vi.fn(async (send) => { onPcm = send; return { echoCancellation: true, headphones: false }; }), releaseMic: vi.fn(), play: vi.fn(), flush: vi.fn(), close: vi.fn() };
  const voice = new VoiceController(SESSION, async () => ({ baseUrl: "http://127.0.0.1", token: "synthetic" }), audio, () => {
    const socket = new Socket(); sockets.push(socket); queueMicrotask(() => { socket.readyState = 1; socket.onopen?.(); }); return socket;
  });
  const capture = { ...typedCapture("", { sessionId: SESSION, purpose: "question", confirmed: false }), source: "voice" as const };
  const requests: { path: string; method: string }[] = []; let release: ((response: Response) => void) | null = null;
  let deferred = pending;
  const commands = new CommandClient({ endpoint: async () => ({ baseUrl: "http://127.0.0.1", token: "synthetic" }), fetch: (async (url, init) => {
    const path = new URL(String(url)).pathname, method = init?.method ?? "GET"; requests.push({ path, method });
    if (method === "DELETE") return new Response(null, { status: 204 });
    if (path.endsWith("/dictations") && deferred) { deferred = false; return new Promise<Response>((done) => { release = done; }); }
    return Response.json(path.endsWith("/captures") ? { captures: [] } : capture);
  }) as typeof fetch });
  const speech = new SpeechController(SESSION, commands, voice, { available: () => true, subscribe: () => () => undefined, speak: () => () => undefined }, true);
  controllers.push(speech); const f = new Fixture(), sendCapture = vi.fn(() => "cli_typed");
  const session = { sessionId: SESSION, commands, sendCapture, discardFailed: vi.fn() } as unknown as SessionController;
  render(<LocaleProvider locale="en"><div data-theme={theme}><StoreProvider holder={f.holder} session={session}><SpeechToolsProvider controller={speech}>
    <VoiceBar controller={voice} /><Composer sessionId={SESSION} />
  </SpeechToolsProvider></StoreProvider></div></LocaleProvider>);
  return { voice, speech, audio, sendCapture, requests, pcm: (bytes: ArrayBuffer) => onPcm(bytes), sockets, release: () => release?.(Response.json(capture)) };
}
const cases = MICROPHONE_REASONS.flatMap((reason) => ["light", "dark"].flatMap((theme) => ["talk", "dictation", "pending", "finishing"].map((phase) => ({ reason, theme, phase }))));
test.each(cases)("uxs34_mic_errors_keep_typing: $reason $theme $phase", async ({ reason, theme, phase }) => {
  const gallery = STATES.filter((s) => s.component === "VoiceBar" && s.state === "error-retriable");
  expect(new Set(gallery.map((s) => (s.payload as { reason: string }).reason))).toEqual(new Set(MICROPHONE_REASONS));
  const s = setup(theme, phase === "pending"), editor = await screen.findByRole("textbox", { name: "Message to the tutor" });
  paste(editor, "Keep my draft"); await waitFor(() => expect(editor.textContent).toContain("Keep my draft"));
  if (phase === "talk") {
    await act(() => s.voice.open());
    if (reason !== "voice.too_noisy") {
      const name = reason.endsWith("missing") ? "NotFoundError" : reason.endsWith("denied") ? "NotAllowedError" : "NotReadableError";
      vi.mocked(s.audio.capture).mockRejectedValueOnce(Object.assign(new Error("synthetic microphone failure"), { name }));
    }
    await act(() => s.voice.ptt(true));
    if (reason === "voice.too_noisy") act(() => s.voice.event({ type: "voice.state", state: "unavailable", reason_key: reason }));
  } else if (phase === "pending") {
    let starting: Promise<void> = Promise.resolve(); act(() => { starting = s.speech.beginDictation("question"); });
    await waitFor(() => expect(s.requests.some((r) => r.path.endsWith("/dictations"))).toBe(true));
    act(() => s.voice.event({ type: "voice.state", state: "unavailable", reason_key: reason }));
    expect(s.speech.getState().dictation).toBe("idle");
    await act(async () => { s.release(); await starting; });
    await waitFor(() => expect(s.requests.some((r) => r.method === "DELETE")).toBe(true));
    expect(s.audio.capture).not.toHaveBeenCalled();
  } else {
    await act(() => s.speech.beginDictation("question")); expect(s.speech.getState().dictation).toBe("listening");
    if (phase === "finishing") act(() => s.speech.endDictation());
    act(() => s.voice.event({ type: "voice.state", state: "unavailable", reason_key: reason }));
  }
  expect(s.speech.getState().dictation).toBe("idle");
  expect(screen.getAllByText(copies[reason] ?? "missing canonical copy").length).toBeGreaterThan(0);
  expect(vi.mocked(s.audio.releaseMic).mock.calls.length + vi.mocked(s.audio.close).mock.calls.length).toBeGreaterThan(0); expect(editor.contentEditable).toBe("true");
  expect(editor.textContent).toContain("Keep my draft"); expect(s.sendCapture).not.toHaveBeenCalled();
  s.pcm(new ArrayBuffer(4800)); expect(s.sockets.flatMap((socket) => socket.send.mock.calls).some((args) => (args[0] as unknown) instanceof ArrayBuffer)).toBe(false);
  const captures = vi.mocked(s.audio.capture).mock.calls.length;
  expect(fireEvent.keyDown(editor, { key: " ", code: "Space" })).toBe(true); fireEvent.keyUp(editor, { key: " ", code: "Space" });
  expect(s.audio.capture).toHaveBeenCalledTimes(captures);
  paste(editor, " after error");
  expect(editor.textContent).toContain("Keep my draft after error");
  const send = screen.getByRole("button", { name: "Send" }); expect(send.hasAttribute("disabled")).toBe(false);
  // A fresh explicit press retries capture; cancellation still preserves typing.
  await act(() => s.speech.beginDictation("question")); expect(s.speech.getState().dictation).toBe("listening");
  act(() => s.speech.cancelDictation()); expect(editor.textContent).toContain("Keep my draft after error");
  fireEvent.click(send);
  expect(s.sendCapture).toHaveBeenCalledWith(expect.objectContaining({ source: "pasted_text", text: "Keep my draft after error", status: "confirmed" }), "ask", expect.any(Array));
}, 10000);
