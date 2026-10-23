import { describe, expect, it, test, vi } from "vitest";
import { VoiceController, type VoiceAudio, type VoiceSocket } from "../src/voice.js";

class Socket implements VoiceSocket {
  binaryType: BinaryType = "blob";
  readyState = 0;
  bufferedAmount = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  sent: (string | ArrayBuffer)[] = [];
  send(data: string | ArrayBuffer): void { this.sent.push(data); }
  close(): void { this.readyState = 3; this.onclose?.(); }
  controls(): Record<string, unknown>[] { return this.sent.filter((item) => typeof item === "string").map((item) => JSON.parse(item)); }
}

// VOC-26 lets the voice socket reach only the loopback core origin, so these tests name loopback without a port
// (the ARC-19 bundle scan forbids a hard-coded loopback port anywhere in a client package).
const CORE = "http://127.0.0.1";
function setup(baseUrl = CORE) {
  let onPcm: (pcm: ArrayBuffer) => void = () => undefined;
  const audio: VoiceAudio = { activate: vi.fn(), capture: vi.fn(async (send) => {
    onPcm = send; return { echoCancellation: true, headphones: false };
  }), releaseMic: vi.fn(), play: vi.fn(), flush: vi.fn(), close: vi.fn() };
  const sockets: Socket[] = [];
  const factory = vi.fn((_url: string, _protocols: string[]) => {
    const socket = new Socket(); sockets.push(socket);
    queueMicrotask(() => { socket.readyState = 1; socket.onopen?.(); });
    return socket;
  });
  const controller = new VoiceController("ses_one", async () => ({ baseUrl, token: "launch-token",
    headers: { "X-Profile-Token": "profile-token" } }), audio, factory);
  return { controller, audio, sockets, factory, pcm: (value: ArrayBuffer) => onPcm(value) };
}

describe("voice session transport", () => {
  it("keeps dictation separate from talk and releases a late microphone permission grant", async () => {
    const { controller, audio, sockets } = setup();
    let grant: ((value: { echoCancellation: boolean; headphones: boolean }) => void) | undefined;
    audio.capture = vi.fn(() => new Promise((resolve) => { grant = resolve; }));
    const pressing = controller.dictate("cap_draft", true);
    await vi.waitFor(() => expect(grant).toBeDefined());
    await controller.dictate("cap_draft", false);
    grant?.({ echoCancellation: true, headphones: false }); await pressing;
    expect(audio.releaseMic).toHaveBeenCalled();
    expect(sockets[0]?.controls()).toContainEqual({ type: "dictate", capture_id: "cap_draft", pressed: true });
    expect(sockets[0]?.controls().some((frame) => frame.type === "ptt")).toBe(false);
    controller.event({ type: "voice.state", state: "listening" });
    controller.event({ type: "voice.state", state: "idle" });
    audio.capture = vi.fn(async () => ({ echoCancellation: true, headphones: false }));
    await controller.ptt(true);
    expect(sockets[0]?.controls()).toContainEqual({ type: "ptt", pressed: true }); controller.close();
  });
  it("cancels dictation on permission refusal and never sends audio or a talk request", async () => {
    const { controller, audio, sockets } = setup();
    audio.capture = vi.fn(async () => { throw new Error("NotAllowedError"); });
    await controller.dictate("cap_draft", true);
    expect(controller.getState().reason).toBe("voice.microphone_unavailable");
    expect(sockets[0]?.controls()).toContainEqual({ type: "stop" });
    expect(sockets[0]?.sent.some((frame) => frame instanceof ArrayBuffer)).toBe(false);
    expect(sockets[0]?.controls().some((frame) => frame.type === "ptt")).toBe(false); controller.close();
  });
  it("settles an opening connection when voice is turned off before accept", async () => {
    const { audio } = setup();
    const socket = new Socket();
    const controller = new VoiceController("ses_one", async () => ({ baseUrl: CORE, token: "test" }),
      audio, () => socket);
    const opening = controller.open();
    await vi.waitFor(() => expect(socket.onopen).not.toBeNull());
    controller.close();
    await opening;
    expect(controller.getState().connected).toBe(false);
    expect(socket.readyState).toBe(3);
  });
  it("opens only the core and offers credentials exclusively as subprotocols", async () => {
    const { controller, factory, sockets } = setup();
    await controller.open();
    expect(factory).toHaveBeenCalledWith("ws://127.0.0.1/v1/sessions/ses_one/voice",
      ["jana.voice.1", "jana.bearer.launch-token", "jana.profile.profile-token"]);
    expect(sockets[0]?.binaryType).toBe("arraybuffer");
    expect(controller.getState().connected).toBe(true);
    controller.close();
  });
  it("requests the microphone on talk, drops closed capture audio, and releases it on key-up", async () => {
    const { controller, audio, sockets, pcm } = setup();
    await controller.open();
    expect(audio.capture).not.toHaveBeenCalled();
    await controller.ptt(true);
    const buffer = new ArrayBuffer(4800);
    pcm(buffer);
    expect(sockets[0]?.sent).toContain(buffer);
    await controller.ptt(false);
    expect(audio.releaseMic).toHaveBeenCalled();
    pcm(new ArrayBuffer(4800));
    expect(sockets[0]?.sent.filter((item) => item instanceof ArrayBuffer)).toHaveLength(1);
    controller.close();
  });
  it("closes a capture granted after the user released the key", async () => {
    const { controller, audio } = setup();
    let grant: ((value: { echoCancellation: boolean; headphones: boolean }) => void) | undefined;
    audio.capture = vi.fn(() => new Promise((resolve) => { grant = resolve; }));
    await controller.open();
    const pressed = controller.ptt(true);
    await vi.waitFor(() => expect(grant).toBeDefined());
    await controller.ptt(false);
    grant?.({ echoCancellation: true, headphones: false });
    await pressed;
    expect(audio.releaseMic).toHaveBeenCalledTimes(2);
    controller.close();
  });
  it("reports the binary response tag and flushes the corresponding queue", async () => {
    const { controller, audio, sockets } = setup();
    await controller.open();
    const socket = sockets[0];
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("resp_test"));
    const frame = new Uint8Array(20);
    frame.set(new Uint8Array(digest, 0, 16));
    socket?.onmessage?.({ data: frame.buffer });
    await vi.waitFor(() => expect(audio.play).toHaveBeenCalledOnce());
    const play = vi.mocked(audio.play).mock.calls[0];
    play?.[2](0, false);
    expect(socket?.controls().at(-1)).toEqual({ type: "playback", response_id: play?.[0], played_ms: 0, ended: false });
    socket?.onmessage?.({ data: JSON.stringify({ type: "flush", response_id: "resp_test" }) });
    await vi.waitFor(() => expect(audio.flush).toHaveBeenCalledWith(play?.[0]));
    controller.close();
  });
  it("ignores socket generations that have already closed", async () => {
    const { controller, audio, sockets } = setup();
    await controller.open();
    const old = sockets[0];
    controller.close();
    await controller.open();
    old?.onmessage?.({ data: new ArrayBuffer(20) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(audio.play).not.toHaveBeenCalled();
    controller.close();
  });
  it("releases all resources on a profile/session close", async () => {
    const { controller, audio, sockets } = setup();
    await controller.mode("hands_free");
    expect(audio.capture).toHaveBeenCalledOnce();
    controller.close();
    expect(audio.close).toHaveBeenCalled();
    expect(sockets[0]?.readyState).toBe(3);
    expect(controller.getState().connected).toBe(false);
  });
  it("rejects an external core URL before constructing a socket", async () => {
    const { controller, factory, audio } = setup("https://external.invalid");
    await expect(controller.open()).rejects.toThrow("voice_unavailable");
    expect(factory).not.toHaveBeenCalled();
    expect(audio.capture).not.toHaveBeenCalled();
  });
});

const audioFrames = (socket: Socket | undefined) => socket?.sent.filter((item) => item instanceof ArrayBuffer) ?? [];
const named = (name: string) => Object.assign(new Error(name), { name });
const CALM = { type: "notice", notice_id: "ntc_one", level: "info", code: "calm_screen", message_key: "safety.calm_screen", params: {}, action: null };

describe("VOC-15", () => {
  // The release is synchronous, so it lands well inside the VOC-15 budget for every way of leaving capture.
  test("voc15_mic_released", async () => {
    // Leaving voice mode (hands-free back to push-to-talk) and profile close release the mic.
    const leaving = setup();
    await leaving.controller.mode("hands_free");
    vi.mocked(leaving.audio.releaseMic).mockClear();
    await leaving.controller.mode("push_to_talk");
    expect(leaving.audio.releaseMic).toHaveBeenCalled();
    leaving.pcm(new ArrayBuffer(4800));
    expect(audioFrames(leaving.sockets[0])).toHaveLength(0);
    leaving.controller.close();
    expect(leaving.audio.close).toHaveBeenCalled();

    // Releasing the dictation control releases the mic and drops later audio.
    const dictating = setup();
    await dictating.controller.dictate("cap_draft", true);
    vi.mocked(dictating.audio.releaseMic).mockClear();
    await dictating.controller.dictate("cap_draft", false);
    expect(dictating.audio.releaseMic).toHaveBeenCalled();
    dictating.pcm(new ArrayBuffer(4800));
    expect(audioFrames(dictating.sockets[0])).toHaveLength(0);
    dictating.controller.close();

    // App focus loss in hands-free: the mic is released, audio stops, and the core leaves hands-free listening.
    const hands = setup();
    await hands.controller.mode("hands_free");
    hands.controller.think(true);
    vi.mocked(hands.audio.releaseMic).mockClear();
    hands.controller.focusLost();
    expect(hands.audio.releaseMic).toHaveBeenCalled();
    hands.pcm(new ArrayBuffer(4800));
    expect(audioFrames(hands.sockets[0])).toHaveLength(0);
    expect(hands.sockets[0]?.controls().slice(-2)).toEqual([{ type: "think", pressed: false }, { type: "mode", mode: "push_to_talk" }]);
    expect(hands.controller.getState().mode).toBe("hands_free");
    // Coming back reopens hands-free capture.
    await hands.controller.focusGained();
    expect(hands.audio.capture).toHaveBeenCalledTimes(2);
    expect(hands.sockets[0]?.controls()).toContainEqual({ type: "mode", mode: "hands_free" });
    hands.pcm(new ArrayBuffer(4800));
    expect(audioFrames(hands.sockets[0])).toHaveLength(1);
    hands.controller.close();

    // App focus loss while push-to-talk is held.
    const talk = setup();
    await talk.controller.ptt(true);
    vi.mocked(talk.audio.releaseMic).mockClear();
    talk.controller.focusLost();
    expect(talk.audio.releaseMic).toHaveBeenCalled();
    expect(talk.sockets[0]?.controls().at(-1)).toEqual({ type: "ptt", pressed: false });
    talk.pcm(new ArrayBuffer(4800));
    expect(audioFrames(talk.sockets[0])).toHaveLength(0);
    await talk.controller.focusGained();
    expect(talk.audio.capture).toHaveBeenCalledOnce(); // push-to-talk waits for the next press
    talk.controller.close();

    // App focus loss while the dictation control is held.
    const held = setup();
    await held.controller.dictate("cap_draft", true);
    vi.mocked(held.audio.releaseMic).mockClear();
    held.controller.focusLost();
    expect(held.audio.releaseMic).toHaveBeenCalled();
    expect(held.sockets[0]?.controls().at(-1)).toEqual({ type: "dictate", capture_id: "cap_draft", pressed: false });
    expect(held.sockets[0]?.controls().some((frame) => frame.type === "ptt")).toBe(false);
    held.pcm(new ArrayBuffer(4800));
    expect(audioFrames(held.sockets[0])).toHaveLength(0);
    // The later release from the dictation control does not repeat the control.
    await held.controller.dictate("cap_draft", false);
    expect(held.sockets[0]?.controls().filter((frame) => frame.type === "dictate" && frame.pressed === false)).toHaveLength(1);
    held.controller.close();
  });
});

describe("VOC-16", () => {
  test("voc16_mic_error_states", async () => {
    const cases: [Error, string][] = [
      [named("NotFoundError"), "voice.microphone_missing"], [named("OverconstrainedError"), "voice.microphone_missing"],
      [named("NotAllowedError"), "voice.microphone_denied"], [named("SecurityError"), "voice.microphone_denied"],
      [named("NotReadableError"), "voice.microphone_unavailable"],
    ];
    for (const [error, reason] of cases) {
      const { controller, audio, sockets } = setup();
      audio.capture = vi.fn(async () => { throw error; });
      await controller.ptt(true);
      expect(controller.getState()).toMatchObject({ state: "unavailable", reason });
      expect(sockets[0]?.controls().at(-1)).toEqual({ type: "ptt", pressed: false });
      expect(audio.releaseMic).toHaveBeenCalled();
      // No dead end: the next press tries the microphone again.
      audio.capture = vi.fn(async () => ({ echoCancellation: true, headphones: false }));
      await controller.ptt(true);
      expect(controller.getState()).toMatchObject({ reason: null });
      expect(audio.capture).toHaveBeenCalledOnce();
      controller.close();
    }
    // A hands-free microphone failure returns to push-to-talk so the core stops listening.
    const hands = setup();
    hands.audio.capture = vi.fn(async () => { throw named("NotAllowedError"); });
    await hands.controller.mode("hands_free");
    expect(hands.controller.getState()).toMatchObject({ mode: "push_to_talk", reason: "voice.microphone_denied" });
    expect(hands.sockets[0]?.controls().at(-1)).toEqual({ type: "mode", mode: "push_to_talk" });
    hands.controller.close();
    // "Too noisy" has no client detector: the core names it as the reason of an unavailable state.
    const noisy = setup();
    await noisy.controller.open();
    noisy.controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.too_noisy" });
    expect(noisy.controller.getState().reason).toBe("voice.too_noisy");
    noisy.controller.close();
  });
});

describe("VOC-14", () => {
  test("turning voice on again after a give-up reconnects", async () => {
    const { controller, sockets } = setup();
    await controller.open();
    controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.stopped_working" });
    expect(controller.getState()).toMatchObject({ state: "unavailable", reason: "voice.stopped_working" });
    await controller.restart();
    expect(sockets).toHaveLength(2);
    expect(sockets[0]?.readyState).toBe(3);
    expect(controller.getState()).toMatchObject({ connected: true, state: "idle", reason: null });
    controller.close();
  });
});

describe("VOC-20", () => {
  test("a calm screen notice releases the mic and holds voice idle until the student goes back", async () => {
    const { controller, audio, sockets, pcm } = setup();
    await controller.mode("hands_free");
    vi.mocked(audio.releaseMic).mockClear();
    controller.event(CALM);
    expect(audio.releaseMic).toHaveBeenCalled();
    expect(controller.getState().state).toBe("idle");
    pcm(new ArrayBuffer(4800));
    expect(audioFrames(sockets[0])).toHaveLength(0);
    const controls = sockets[0]?.controls().length;
    // Nothing reopens capture or sends a control that would end the core's calm hold.
    await controller.ptt(true);
    await controller.mode("hands_free");
    await controller.dictate("cap_draft", true);
    controller.focusLost();
    await controller.focusGained();
    expect(audio.capture).toHaveBeenCalledOnce();
    expect(sockets[0]?.controls()).toHaveLength(controls ?? 0);
    // A reconnect while held does not end the hold either.
    controller.close();
    await controller.open();
    expect(sockets[1]?.controls()).toEqual([]);
    // "Back to my lesson when I'm ready" re-sends the talk mode; push-to-talk works again.
    await controller.resumeAfterCalm();
    expect(sockets[1]?.controls()).toEqual([{ type: "mode", mode: "push_to_talk" }]);
    await controller.ptt(true);
    expect(sockets[1]?.controls()).toContainEqual({ type: "ptt", pressed: true });
    expect(audio.capture).toHaveBeenCalledTimes(2);
    controller.close();
  });
  test("going back reopens hands-free capture", async () => {
    const { controller, audio, sockets } = setup();
    await controller.mode("hands_free");
    controller.event(CALM);
    await controller.resumeAfterCalm();
    expect(sockets[0]?.controls().at(-2)).toEqual({ type: "mode", mode: "hands_free" });
    expect(audio.capture).toHaveBeenCalledTimes(2);
    controller.close();
  });
});

describe("voice reasons", () => {
  test("unknown diagnostics never become student translation keys; catalogued wire reasons keep their copy", async () => {
    const { controller } = setup();
    await controller.open();
    // Transport reasons the core or client sends have VOC-14 copy ("Voice stopped working") and stay as they are.
    for (const reason of ["voice.endpoint_error", "voice.protocol_error", "voice.disconnected"]) {
      controller.event({ type: "voice.state", state: "unavailable", reason_key: reason });
      expect(controller.getState().reason).toBe(reason);
    }
    // A diagnostic or a reason this build has no copy for shows the VOC-14 give-up copy, never the raw text.
    for (const reason of ["private diagnostic", "voice.some_new_reason"]) {
      controller.event({ type: "voice.state", state: "unavailable", reason_key: reason });
      expect(controller.getState().reason).toBe("voice.stopped_working");
    }
    controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.microphone_unavailable" });
    expect(controller.getState().reason).toBe("voice.microphone_unavailable"); controller.close();
  });
});

describe("conversation start (VOC-49, D126)", () => {
  it("voc49_shortcut_toggles_conversation: one action starts hands-free listening, the same action ends it", async () => {
    const { controller, audio, sockets, pcm } = setup();
    await controller.conversation();
    expect(controller.getState()).toMatchObject({ connected: true, mode: "hands_free" });
    expect(sockets[0]?.controls()).toContainEqual({ type: "mode", mode: "hands_free" });
    expect(audio.capture).toHaveBeenCalledOnce();
    pcm(new ArrayBuffer(960));
    expect(sockets[0]?.sent.some((frame) => frame instanceof ArrayBuffer)).toBe(true);
    await controller.conversation();
    expect(controller.getState()).toMatchObject({ connected: false, mode: "push_to_talk" });
    expect(audio.close).toHaveBeenCalled();
    expect(sockets[0]?.controls()).toContainEqual({ type: "stop" });
  });
  it("voc49_no_listening_before_start: nothing captures or is sent before a start, and a calm hold refuses it", async () => {
    const { controller, audio, sockets } = setup();
    await controller.open();
    expect(audio.capture).not.toHaveBeenCalled();
    expect(sockets[0]?.controls().some((frame) => frame.type === "wake")).toBe(false);
    controller.event(CALM);
    controller.close();
    await controller.conversation();
    expect(audio.capture).not.toHaveBeenCalled();
    controller.close();
  });
});

describe("conversation place (VOC-53, D130)", () => {
  test("the open chat is named on the socket, again after a reconnect, and cleared on leaving", async () => {
    const { controller, sockets } = setup();
    controller.setPlace({ place: "ask" }); // before connecting: sent once the socket opens
    await controller.open();
    expect(sockets[0]?.controls().filter((c) => c.type === "place")).toEqual([{ type: "place", place: "ask" }]);
    controller.setPlace({ place: "ask" }); // the same place is not sent again
    controller.setPlace({ place: "study", source_id: "src_01JZ0000000000000000000001", revision: 2, open: "grant" });
    controller.setPlace(null);
    expect(sockets[0]?.controls().filter((c) => c.type === "place")).toEqual([
      { type: "place", place: "ask" },
      { type: "place", place: "study", source_id: "src_01JZ0000000000000000000001", revision: 2, open: "grant" },
      { type: "place", place: null }]);
    controller.setPlace({ place: "ask" });
    controller.close();
    await controller.open();
    expect(sockets[1]?.controls().find((c) => c.type === "place")).toEqual({ type: "place", place: "ask" });
    expect(controller.place).toEqual({ place: "ask" });
    controller.close();
  });
});

