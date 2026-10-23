import { describe, expect, it, vi } from "vitest";
import { SpeechController, type LocalSpeech } from "../src/speech.js";
import { CommandClient } from "../src/stream/commands.js";
import { typedCapture } from "../src/capture.js";
import type { VoiceController, VoiceView } from "../src/voice.js";

const draft = { ...typedCapture("", { sessionId: "ses_test", purpose: "question", confirmed: false }), source: "voice" as const };
const spoken = { utterance_id: "utt_test", text: "x squared equals nine.", transport: "os" };
function setup(hasPack = false, available = true, defer = false, dictation = hasPack) {
  let callbacks: Parameters<LocalSpeech["speak"]>[1] | null = null;
  const cancel = vi.fn();
  const local: LocalSpeech = { available: () => available, subscribe: vi.fn(() => vi.fn()),
    speak: vi.fn((_text, handlers) => { callbacks = handlers; return cancel; }) };
  const voiceView: VoiceView = { connected: true, state: "idle", mode: "push_to_talk", reason: null,
    student: "", tentative: "", tutor: "", words: [], captionItem: null, playedMs: 0, pointer: null, writing: null };
  const voice = { activate: vi.fn(), subscribe: vi.fn(() => vi.fn()), getState: () => voiceView, open: vi.fn(async () => undefined),
    event: vi.fn(), close: vi.fn(), speak: vi.fn(async () => undefined), stop: vi.fn(), stopRead: vi.fn(), dictate: vi.fn(async () => undefined) };
  const requests: { path: string; body: Record<string, unknown>; method: string; key: string | null }[] = [];
  let respond: (path: string, method: string) => Promise<Response> = async (path, method) =>
    new Response(method === "DELETE" || path.endsWith("/playback") ? null : JSON.stringify(
      path.endsWith("/utterances") ? { ...spoken, transport: hasPack ? "sidecar" : "os" } : draft),
    { status: method === "DELETE" || path.endsWith("/playback") ? 204 : 200 });
  const fetchImpl = vi.fn(async (url, init) => {
    const path = new URL(String(url)).pathname, method = init?.method ?? "GET";
    requests.push({ path, method, key: new Headers(init?.headers).get("idempotency-key"), body: init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {} });
    return respond(path, method);
  }) as unknown as typeof fetch;
  const commands = new CommandClient({ endpoint: async () => ({ baseUrl: "http://core.test", token: "test" }), fetch: fetchImpl });
  const controller = new SpeechController("ses_test", commands, voice as unknown as VoiceController, local, hasPack, defer, dictation);
  return { controller, local, voice, voiceView, cancel, requests, callbacks: () => callbacks!,
    respond: (handler: typeof respond) => { respond = handler; } };
}

describe("read-aloud and dictation", () => {
  it("uses only the core's spoken text, reports word positions, and restarts without cancelling a turn", async () => {
    const s = setup();
    await s.controller.read("prt_accepted");
    expect(s.local.speak).toHaveBeenCalledWith(spoken.text, expect.any(Object));
    s.callbacks().start(); s.callbacks().boundary(2, 300);
    expect(s.controller.getState().charIndex).toBe(2);
    s.controller.stopReading();
    expect(s.cancel).toHaveBeenCalledOnce();
    await s.controller.read("prt_accepted");
    expect(s.local.speak).toHaveBeenCalledTimes(2);
    expect(s.voice.stop).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(s.requests.some((r) => r.body.phase === "stop")).toBe(true));
    expect(s.requests.some((r) => r.path.endsWith("/turns"))).toBe(false);
    s.controller.close();
  });
  it("ignores late synthesis callbacks and a pending response after profile close", async () => {
    const s = setup();
    await s.controller.read("prt_accepted");
    const old = s.callbacks();
    s.controller.close(); old.boundary(7, 1000); old.end();
    expect(s.controller.getState().reading).toBe(false);
    const pending = setup();
    let resolve: ((response: Response) => void) | undefined;
    pending.respond(() => new Promise((done) => { resolve = done; }));
    const opening = pending.controller.read("prt_accepted");
    await vi.waitFor(() => expect(resolve).toBeDefined());
    pending.controller.close(); resolve?.(new Response(JSON.stringify(spoken)));
    await opening;
    expect(pending.local.speak).not.toHaveBeenCalled();
  });
  it("voc14_tts_failure_fallback", async () => {
    const absent = setup(false, false);
    expect(absent.controller.getState().available).toBe(false);
    await absent.controller.read("prt_accepted");
    expect(absent.local.speak).not.toHaveBeenCalled(); absent.controller.close();
    const s = setup(); await s.controller.read("prt_accepted"); s.callbacks().error();
    expect(s.controller.getState().error).toBe("voice.synthesiser_unavailable");
    expect(s.controller.getState().reading).toBe(false); s.controller.close();
  });
  it("queues pack read-aloud while a tutor response is active, preserving that connection", async () => {
    const s = setup(true); s.voiceView.state = "speaking";
    await s.controller.read("prt_accepted");
    expect(s.voice.close).not.toHaveBeenCalled();
    expect(s.voice.speak).toHaveBeenCalledWith(spoken.utterance_id);
    expect(s.local.speak).not.toHaveBeenCalled();
    s.controller.stopReading();
    expect(s.voice.stopRead).toHaveBeenCalledWith(spoken.utterance_id);
    expect(s.voice.stop).not.toHaveBeenCalled();
    expect(s.voice.close).not.toHaveBeenCalled(); s.controller.close();
  });
  it("refuses capture setup failures before requesting microphone permission", async () => {
    const s = setup(true);
    s.respond(async () => new Response(JSON.stringify({ error: { code: "feature_disabled", retryable: false } }), { status: 403 }));
    await s.controller.beginDictation("question");
    expect(s.voice.dictate).not.toHaveBeenCalled();
    expect(s.controller.getState().error).toBe("voice.unavailable");
    expect(s.controller.getState().draft).toBeNull(); s.controller.close();
  });
  it("returns an editable unconfirmed capture and never submits it", async () => {
    const s = setup(true);
    s.respond(async (_path, method) => new Response(method === "DELETE" ? null : JSON.stringify(
      method === "GET" ? { ...draft, text: "x squared", status: "awaiting_confirmation" } : draft),
    { status: method === "DELETE" ? 204 : 200 }));
    await s.controller.beginDictation("question"); s.controller.endDictation();
    expect(s.voice.dictate).toHaveBeenCalledWith(draft.capture_id, false);
    await vi.waitFor(() => expect(s.controller.getState().dictation).toBe("review"));
    const capture = s.controller.takeDraft();
    expect(capture?.source).toBe("voice"); expect(capture?.confirmation.confirmed).toBe(false);
    expect(s.requests.some((r) => r.path.endsWith("/turns"))).toBe(false); s.controller.close();
  });
  it("cancels pending start on key release and deletes a late capture without opening the mic", async () => {
    const s = setup(true);
    let resolve: ((response: Response) => void) | undefined;
    s.respond(async (_path, method) => method === "DELETE" ? new Response(null, { status: 204 }) :
      new Promise((done) => { resolve = done; }));
    const starting = s.controller.beginDictation("question");
    await vi.waitFor(() => expect(resolve).toBeDefined());
    s.controller.endDictation(); resolve?.(new Response(JSON.stringify(draft))); await starting;
    expect(s.voice.dictate).not.toHaveBeenCalled(); expect(s.controller.getState().draft).toBeNull();
    await vi.waitFor(() => expect(s.requests.some((r) => r.method === "DELETE")).toBe(true)); s.controller.close();
  });
  it("discards a late transcript after cancellation and releases the shared resources on profile close", async () => {
    const s = setup(true);
    let resolve: ((response: Response) => void) | undefined;
    s.respond(async (_path, method) => method === "GET" ? new Promise((done) => { resolve = done; }) :
      new Response(method === "DELETE" ? null : JSON.stringify(draft), { status: method === "DELETE" ? 204 : 200 }));
    await s.controller.beginDictation("question"); s.controller.endDictation();
    await vi.waitFor(() => expect(resolve).toBeDefined());
    s.controller.close(); resolve?.(new Response(JSON.stringify({ ...draft, status: "awaiting_confirmation", text: "late" })));
    await new Promise((done) => setTimeout(done, 0));
    expect(s.controller.getState().draft).toBeNull(); expect(s.voice.stop).toHaveBeenCalled();
    expect(s.voice.close).toHaveBeenCalled();
  });
  it("keeps the specific microphone error copy when dictation cannot open the mic (VOC-16)", async () => {
    const s = setup(true);
    s.voice.dictate = vi.fn(async () => {
      Object.assign(s.voiceView, { state: "unavailable", reason: "voice.microphone_denied" });
    });
    await s.controller.beginDictation("question");
    expect(s.controller.getState()).toMatchObject({ dictation: "idle", error: "voice.microphone_denied" });
    s.controller.close();
  });
  it("shows the couldn't-hear copy for an unreadable dictation transcript (VOC-14)", async () => {
    const s = setup(true);
    s.respond(async (_path, method) => new Response(method === "DELETE" ? null : JSON.stringify(
      method === "GET" ? { ...draft, status: "unreadable" } : draft), { status: method === "DELETE" ? 204 : 200 }));
    await s.controller.beginDictation("question"); s.controller.endDictation();
    await vi.waitFor(() => expect(s.controller.getState().error).toBe("voice.dictation_unheard"));
    expect(s.controller.getState()).toMatchObject({ dictation: "idle", draft: null }); s.controller.close();
  });
  it("a calm screen notice ends reading and dictation without the stop key (VOC-20)", async () => {
    const calm = { type: "notice", notice_id: "ntc_one", code: "calm_screen", level: "info", params: {} };
    const s = setup();
    await s.controller.read("prt_accepted");
    s.controller.voiceEvent(calm);
    expect(s.voice.event).toHaveBeenCalledWith(calm);
    expect(s.cancel).toHaveBeenCalledOnce();
    expect(s.controller.getState().reading).toBe(false); s.controller.close();
    const d = setup(true);
    await d.controller.beginDictation("question");
    d.controller.voiceEvent(calm);
    expect(d.controller.getState().dictation).toBe("idle");
    expect(d.voice.stop).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(d.requests.some((r) => r.method === "DELETE")).toBe(true)); d.controller.close();
  });
});

import { emptyStore, type Store, type TurnRec, type PartRec, type SessionRec } from "../src/store.js";
function accepted(store: Store, id: string, status: TurnRec["status"] = "complete") {
  const turn = `trn_${id}`;
  store.turns[turn] = { turn_id: turn, session_id: "ses_test", status, part_ids: [id] } as TurnRec;
  store.parts[id] = { part_id: id, turn_id: turn, kind: "text", status: "complete", text: id } as PartRec;
  store.sessions.ses_test ??= { turn_ids: [] } as unknown as SessionRec;
  store.sessions.ses_test.turn_ids.push(turn);
}
describe("automatic student read-aloud", () => {
  it("ignores history and pending turns, queues accepted replies and reads each once", async () => {
    const s = setup(), store = emptyStore();
    s.controller.configure({ read_aloud: true }); accepted(store, "history"); s.controller.observe(store);
    accepted(store, "first", "streaming"); s.controller.observe(store); await Promise.resolve();
    expect(s.local.speak).not.toHaveBeenCalled();
    store.turns.trn_first!.status = "complete"; s.controller.observe(store);
    await vi.waitFor(() => expect(s.local.speak).toHaveBeenCalledOnce());
    accepted(store, "second"); s.controller.observe(store); s.controller.observe(store);
    expect(s.local.speak).toHaveBeenCalledOnce(); s.callbacks().end();
    await vi.waitFor(() => expect(s.local.speak).toHaveBeenCalledTimes(2));
    s.callbacks().end(); s.controller.observe(store); await Promise.resolve();
    expect(s.local.speak).toHaveBeenCalledTimes(2); s.controller.close();
  });
  it("voc14_low_power_keeps_on_demand", async () => {
    const s = setup(), store = emptyStore();
    s.controller.configure({ read_aloud: true }); s.controller.observe(store);
    accepted(store, "first"); s.controller.observe(store);
    await vi.waitFor(() => expect(s.local.speak).toHaveBeenCalledOnce());
    accepted(store, "second"); s.controller.observe(store); s.controller.stopReading();
    await Promise.resolve(); expect(s.local.speak).toHaveBeenCalledOnce();
    s.controller.configure({ read_aloud: true, low_power: true }); accepted(store, "third"); s.controller.observe(store);
    await Promise.resolve(); expect(s.local.speak).toHaveBeenCalledOnce();
    await s.controller.read("third"); expect(s.local.speak).toHaveBeenCalledTimes(2); s.controller.close();
  });
  it("waits while the tutor is busy and suppresses replies already spoken in conversation", async () => {
    const s = setup(), store = emptyStore();
    s.controller.configure({ read_aloud: true }); s.controller.observe(store);
    s.voiceView.state = "thinking"; accepted(store, "first"); s.controller.observe(store);
    await Promise.resolve(); expect(s.local.speak).not.toHaveBeenCalled();
    s.voiceView.state = "idle"; s.controller.observe(store);
    await vi.waitFor(() => expect(s.local.speak).toHaveBeenCalledOnce()); s.callbacks().end();
    accepted(store, "spoken");
    s.controller.voiceEvent({ type: "voice.caption", speaker: "tutor", turn_id: "trn_spoken", item_id: null });
    s.controller.observe(store); await Promise.resolve();
    expect(s.local.speak).toHaveBeenCalledOnce(); s.controller.close();
  });
  it("sends only owned content references; note dictation starts no confirmation or tutor request", async () => {
    const s = setup(), source = { kind: "note" as const, note_id: "nt_saved" };
    await s.controller.read(source);
    expect(s.requests[0]?.body).toEqual({ type: "read_content", source });
    expect(s.requests.some((r) => "text" in r.body)).toBe(false); s.controller.close();
    const n = setup(true); await n.controller.beginDictation("question", "note");
    expect(n.requests.find((r) => r.path.endsWith("/dictations"))?.body.destination).toBe("note");
    n.controller.cancelDictation();
    expect(n.requests.some((r) => r.path.endsWith("/confirm") || r.path.endsWith("/turns"))).toBe(false); n.controller.close();
  });
});

describe("read-aloud with a speech pack (D95)", () => {
  it("reads through the OS voice when the pack's voice cannot start", async () => {
    const s = setup(true);
    s.voice.open.mockRejectedValueOnce(new Error("voice_unavailable"));
    s.respond(async (path, method) => new Response(method === "DELETE" || path.endsWith("/playback") ? null
      : JSON.stringify(spoken), { status: method === "DELETE" || path.endsWith("/playback") ? 204 : 200 }));
    await s.controller.read("prt_accepted");
    expect(s.voice.close).toHaveBeenCalled();
    expect(s.local.speak).toHaveBeenCalledWith(spoken.text, expect.any(Object));
    s.callbacks().start();
    expect(s.controller.getState().error).toBeNull(); s.controller.close();
    const silent = setup(true, false);
    silent.voice.open.mockRejectedValueOnce(new Error("voice_unavailable"));
    await silent.controller.read("prt_accepted");
    expect(silent.local.speak).not.toHaveBeenCalled();
    expect(silent.controller.getState().error).toBe("voice.unavailable"); silent.controller.close();
  });
  it("a read-aloud-only pack reads in its voice and offers no dictation", async () => {
    const s = setup(true, true, false, false);
    expect(s.controller.hasPack && !s.controller.canDictate).toBe(true);
    await s.controller.read("prt_accepted");
    expect(s.voice.speak).toHaveBeenCalledWith(spoken.utterance_id);
    await s.controller.beginDictation("question");
    expect(s.requests.some((r) => r.path.endsWith("/dictations"))).toBe(false);
    expect(s.controller.getState().dictation).toBe("idle"); s.controller.close();
  });
});


it("defers platform subscriptions until mount and supports effect cleanup/restart without a leak", () => {
  const s = setup(false, true, true);
  expect(s.local.subscribe).not.toHaveBeenCalled();
  s.controller.activate(); s.controller.activate();
  expect(s.local.subscribe).toHaveBeenCalledOnce();
  s.controller.close(); s.controller.activate();
  expect(s.local.subscribe).toHaveBeenCalledTimes(2);
  s.controller.close();
  expect(s.controller.getState().text).toBe("");
});


it("retries an explicitly saved note with the same idempotency key after a failed response", async () => {
  const s = setup();
  s.respond(async () => new Response(JSON.stringify({ error: { code: "internal_error" } }), { status: 503 }));
  await expect(s.controller.saveNote("A reviewed note")).rejects.toThrow();
  s.respond(async () => new Response(JSON.stringify({ note_id: "nt_saved", text: "A reviewed note", source: "typed", created_at: 0, updated_at: 0 })));
  await s.controller.saveNote("A reviewed note");
  expect(s.requests[0]?.key).toBe(s.requests[1]?.key);
  expect(s.requests[0]?.key).toMatch(/^cli_/);
  s.controller.close();
});
