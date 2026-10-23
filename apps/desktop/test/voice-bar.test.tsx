// The desktop voice bar's unavailable states (VOC-14, VOC-16) and the app focus-loss mic release (VOC-15), against a
// real VoiceController over a fake socket and fake audio devices. No microphone or network is used.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { VoiceController, type VoiceAudio, type VoiceSocket, type VoiceView } from "@jana/client-core";
import { LocaleProvider } from "@jana/ui";
import { VoiceBar } from "../src/VoiceBar.js";
import { NO_VOICE, releaseOnFocusLoss, voiceOfferFrom } from "../src/SpeechTools.js";

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

function setup() {
  let onPcm: (pcm: ArrayBuffer) => void = () => undefined;
  const audio: VoiceAudio = { activate: vi.fn(), capture: vi.fn(async (send) => {
    onPcm = send; return { echoCancellation: true, headphones: false };
  }), releaseMic: vi.fn(), play: vi.fn(), flush: vi.fn(), close: vi.fn() };
  const sockets: Socket[] = [];
  const controller = new VoiceController("ses_one", async () => ({ baseUrl: "http://127.0.0.1", token: "launch-token" }), audio, () => {
    const socket = new Socket(); sockets.push(socket);
    queueMicrotask(() => { socket.readyState = 1; socket.onopen?.(); });
    return socket;
  });
  render(<LocaleProvider locale="en"><VoiceBar controller={controller} /></LocaleProvider>);
  return { controller, audio, sockets, pcm: (value: ArrayBuffer) => onPcm(value) };
}
const named = (name: string) => Object.assign(new Error(name), { name });

afterEach(() => cleanup());

describe("voice bar unavailable states", () => {
  test("each microphone error shows its own copy and leaves hold-to-talk ready for another try (VOC-16)", async () => {
    const copies: [Error | null, string][] = [
      [named("NotFoundError"), "No microphone found. Plug one in or keep typing."],
      [named("NotAllowedError"), "Microphone access is off for this app. Open system settings to allow it."],
      [null, "It's noisy here. Try Hold Space to talk, or hold the mic close and speak clearly."],
    ];
    for (const [error, copy] of copies) {
      const { controller, audio } = setup();
      await act(() => controller.open());
      if (error) {
        audio.capture = vi.fn(async () => { throw error; });
        await act(() => controller.ptt(true));
      } else act(() => controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.too_noisy" }));
      expect(screen.getByText(copy)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Turn voice on again" })).toBeNull();
      expect(screen.getByRole("button", { name: "Hold to talk" })).toBeTruthy();
      act(() => controller.close()); cleanup();
    }
  });
  test("a give-up shows the fallback copy and Turn voice on again reconnects (VOC-14)", async () => {
    const { controller, sockets } = setup();
    await act(() => controller.open());
    act(() => controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.stopped_working" }));
    expect(screen.getByText("Voice stopped working. You can keep typing.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn voice on again" }));
    await vi.waitFor(() => expect(controller.getState()).toMatchObject({ connected: true, state: "idle" }));
    expect(sockets).toHaveLength(2);
    expect(screen.queryByText("Voice stopped working. You can keep typing.")).toBeNull();
    act(() => controller.close());
  });
  test("a lost connection and an unknown reason never show a raw key", async () => {
    const { controller, sockets } = setup();
    await act(() => controller.open());
    act(() => controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.some_new_reason" }));
    expect(screen.getByText("Voice stopped working. You can keep typing.")).toBeTruthy();
    expect(screen.queryByText("voice.some_new_reason")).toBeNull();
    act(() => sockets[0]?.close());
    expect(screen.getByText("Voice stopped working. You can keep typing.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn voice on again" }));
    await vi.waitFor(() => expect(controller.getState().connected).toBe(true));
    act(() => controller.close());
  });
  test("a missing speech pack offers no reconnect", async () => {
    const { controller } = setup();
    await act(() => controller.open());
    act(() => controller.event({ type: "voice.state", state: "unavailable", reason_key: "voice.pack_unavailable" }));
    expect(screen.getByText("Voice isn't available on this computer. You can keep reading and typing.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turn voice on again" })).toBeNull();
    act(() => controller.close());
  });
});

describe("VOC-15", () => {
  test("window blur and a hidden document release the mic in hands-free, and focus brings it back", async () => {
    const { controller, audio, sockets, pcm } = setup();
    const speech = { endDictation: vi.fn(), voice: controller };
    const unwatch = releaseOnFocusLoss(speech);
    await act(() => controller.mode("hands_free"));
    vi.mocked(audio.releaseMic).mockClear();
    act(() => { window.dispatchEvent(new Event("blur")); });
    expect(speech.endDictation).toHaveBeenCalled();
    expect(audio.releaseMic).toHaveBeenCalled();
    pcm(new ArrayBuffer(4800));
    expect(sockets[0]?.sent.some((item) => item instanceof ArrayBuffer)).toBe(false);
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await vi.waitFor(() => expect(audio.capture).toHaveBeenCalledTimes(2));
    vi.mocked(audio.releaseMic).mockClear();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(audio.releaseMic).toHaveBeenCalled();
    hidden.mockRestore();
    unwatch(); act(() => controller.close());
  });
});

// The global voice shortcuts yield to controls, dialogs, composition and modified shortcuts, against a fixed view.
function setupKeys() {
  const view: VoiceView = { connected: true, state: "idle", mode: "push_to_talk", reason: null,
    student: "", tentative: "", tutor: "", words: [], playedMs: 0, captionItem: null, pointer: null, writing: null };
  const controller = { getState: () => view, subscribe: () => () => undefined,
    ptt: vi.fn(async () => undefined), think: vi.fn(), stop: vi.fn(), close: vi.fn() };
  render(<><VoiceBar controller={controller as unknown as VoiceController} />
    <button>Other action</button><input aria-label="Draft" /><div role="dialog"><p>Dialog content</p></div></>);
  return controller;
}

describe("voice keyboard shortcuts", () => {
  test("Space leaves form controls and dialogs to their normal keyboard handlers", () => {
    const controller = setupKeys();
    for (const target of [screen.getByRole("button", { name: "Other action" }), screen.getByRole("textbox"),
      screen.getByText("Dialog content"), screen.getByRole("combobox")]) {
      expect(fireEvent.keyDown(target, { code: "Space" })).toBe(true);
      fireEvent.keyUp(target, { code: "Space" });
    }
    expect(controller.ptt).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(document.body, { code: "Space" })).toBe(false);
    fireEvent.keyUp(document.body, { code: "Space" });
    expect(controller.ptt.mock.calls).toEqual([[true], [false]]);
  });

  test("the talk button supports Space itself and releases the microphone on blur", () => {
    const controller = setupKeys();
    const talk = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.keyDown(talk, { code: "Space" }); fireEvent.keyUp(talk, { code: "Space" });
    fireEvent.blur(talk);
    expect(controller.ptt.mock.calls).toEqual([[true], [false], [false]]);
  });

  test("composition, modifiers, handled shortcuts and dialog Escape are not global voice commands", () => {
    const controller = setupKeys();
    fireEvent.keyDown(document.body, { code: "Space", isComposing: true });
    fireEvent.keyDown(document.body, { code: "Space", ctrlKey: true });
    fireEvent.keyDown(screen.getByText("Dialog content"), { code: "Escape" });
    expect(controller.ptt).not.toHaveBeenCalled(); expect(controller.stop).not.toHaveBeenCalled();
  });
});

describe("what the speech pack offers (D95, VOC-14)", () => {
  test("a read-aloud-only pack reads aloud without dictation or talk; no pack offers nothing", () => {
    expect(voiceOfferFrom(["sse_session", "voice"])).toEqual({ pack: true, dictation: false, talk: false });
    expect(voiceOfferFrom(["voice", "voice_dictation", "voice_tutoring"])).toEqual({ pack: true, dictation: true, talk: true });
    expect(voiceOfferFrom(["voice_dictation", "voice_tutoring"])).toEqual(NO_VOICE);
  });
});

// VOC-49, D126 (as in Codex): the start button and Ctrl+Shift+V (Cmd+Shift+V on macOS) start or end a hands-free
// conversation; inside a text field the shortcut stays paste-as-plain-text. There is no wake word.
describe("conversation start", () => {
  function show(change: Partial<VoiceView>) {
    const view: VoiceView = { connected: false, state: "idle", mode: "push_to_talk", reason: null, student: "",
      tentative: "", tutor: "", words: [], playedMs: 0, captionItem: null, pointer: null, writing: null, ...change };
    const controller = { getState: () => view, subscribe: () => () => undefined, conversation: vi.fn(async () => undefined),
      ptt: vi.fn(async () => undefined), think: vi.fn(), stop: vi.fn(), close: vi.fn(), open: vi.fn(async () => undefined) };
    const shown = render(<><input aria-label="Answer" /><VoiceBar controller={controller as unknown as VoiceController} /></>);
    return { controller, shown };
  }
  test("voc49_shortcut_toggles_conversation", () => {
    const { controller, shown } = show({});
    fireEvent.click(screen.getByRole("button", { name: "Start a conversation" }));
    expect(screen.getByText(/or press (Ctrl\+Shift\+V|⌘⇧V)/)).toBeTruthy();
    fireEvent.keyDown(document.body, { code: "KeyV", ctrlKey: true, shiftKey: true });
    fireEvent.keyDown(document.body, { code: "KeyV", metaKey: true, shiftKey: true });
    expect(controller.conversation).toHaveBeenCalledTimes(3);
    shown.unmount();
    const on = show({ connected: true, mode: "hands_free", state: "listening" });
    fireEvent.click(screen.getByRole("button", { name: "End conversation" }));
    expect(on.controller.conversation).toHaveBeenCalledOnce();
    expect(on.shown.container.querySelector("[data-wake-armed]")).toBeNull();
    on.shown.unmount();
  });
  test("voc49_no_listening_before_start: the shortcut leaves text fields to paste, and other combinations do nothing", () => {
    const { controller, shown } = show({});
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Answer" }), { code: "KeyV", ctrlKey: true, shiftKey: true });
    fireEvent.keyDown(document.body, { code: "KeyV", ctrlKey: true });
    fireEvent.keyDown(document.body, { code: "KeyV", ctrlKey: true, shiftKey: true, altKey: true });
    fireEvent.keyDown(document.body, { code: "KeyV", shiftKey: true });
    expect(controller.conversation).not.toHaveBeenCalled();
    expect(controller.open).not.toHaveBeenCalled();
    shown.unmount();
  });
});
