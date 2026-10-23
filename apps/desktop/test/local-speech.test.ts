import { describe, expect, it, vi } from "vitest";
import { BrowserLocalSpeech, onlyCompactVoices, rankVoices, voiceQuality } from "../src/local-speech.js";

describe("the fallback system voice (VOC-18)", () => {
  const voice = (voiceURI: string, name: string, extra: { lang?: string; localService?: boolean; default?: boolean } = {}) =>
    ({ voiceURI, name, lang: extra.lang ?? "en-GB", localService: extra.localService ?? true, default: extra.default ?? false });
  const LIST = [
    voice("compact", "Daniel"),
    voice("os-default", "Karen", { default: true, lang: "en-AU" }),
    voice("network", "Google UK English Female (Premium)", { localService: false }),
    voice("enhanced", "Serena (Enhanced)"),
    voice("french", "Thomas (Premium)", { lang: "fr-FR" }),
    voice("premium", "Ava (Premium)", { lang: "en-US" }),
    voice("natural", "Microsoft Libby (Natural)"),
  ];

  it("ranks premium, then enhanced or natural, then the computer's default voice, never a network voice", () => {
    expect(voiceQuality({ name: "Ava (Premium)" })).toBeGreaterThan(voiceQuality({ name: "Serena (Enhanced)" }));
    expect(voiceQuality({ name: "Microsoft Libby (Natural)" })).toBe(voiceQuality({ name: "Serena (Enhanced)" }));
    expect(voiceQuality({ name: "Daniel" })).toBe(0);
    expect(rankVoices(LIST).map((v) => v.voiceURI)).toEqual(["premium", "enhanced", "natural", "os-default", "compact"]);
  });

  it("reads aloud in the best installed voice unless the student chose one that is installed", () => {
    let utterance!: SpeechSynthesisUtterance;
    const synthesis = { getVoices: () => LIST, speak: vi.fn(), cancel: vi.fn() };
    const local = new BrowserLocalSpeech(synthesis as unknown as SpeechSynthesis, (text) => {
      utterance = { text } as SpeechSynthesisUtterance; return utterance;
    });
    const callbacks = { start() {}, boundary() {}, end() {}, error() {} };
    local.speak("Accepted words", callbacks);
    expect(utterance.voice?.voiceURI).toBe("premium");
    expect(local.voices()[0]?.id).toBe("premium");
    local.configure(1, "compact"); local.speak("Accepted words", callbacks);
    expect(utterance.voice?.voiceURI).toBe("compact");
    local.configure(1, "network"); local.speak("Accepted words", callbacks);
    expect(utterance.voice?.voiceURI).toBe("premium");
    expect(local.onlyCompact()).toBe(false);
  });

  it("knows when only compact voices are installed", () => {
    expect(onlyCompactVoices([voice("a", "Daniel"), voice("b", "Karen", { default: true }), voice("c", "Ava (Premium)", { localService: false })])).toBe(true);
    expect(onlyCompactVoices([voice("a", "Daniel"), voice("d", "Serena (Enhanced)")])).toBe(false);
    expect(onlyCompactVoices([])).toBe(false);
  });
});

function setup(localService = true) {
  let utterance: SpeechSynthesisUtterance;
  const synthesis = { getVoices: () => [{ name: "English", lang: "en-GB", localService }],
    addEventListener: vi.fn(), removeEventListener: vi.fn(), cancel: vi.fn(), speak: vi.fn(), paused: false };
  const adapter = new BrowserLocalSpeech(synthesis as unknown as SpeechSynthesis, (text) => {
    utterance = { text } as SpeechSynthesisUtterance; return utterance;
  });
  const callbacks = { start: vi.fn(), boundary: vi.fn(), end: vi.fn(), error: vi.fn() };
  return { adapter, synthesis, callbacks, utterance: () => utterance };
}

describe("offline OS speech", () => {
  it("refuses network/default voices before giving them any text", () => {
    const s = setup(false);
    expect(s.adapter.available()).toBe(false);
    expect(() => s.adapter.speak("Already accepted text.", s.callbacks)).toThrow("local_voice_unavailable");
    expect(s.synthesis.speak).not.toHaveBeenCalled();
  });
  it("uses an installed voice, forwards word boundaries and ignores late events after cancellation", () => {
    const s = setup(), cancel = s.adapter.speak("Accepted text.", s.callbacks);
    const utterance = s.utterance(), late = utterance.onboundary;
    utterance.onstart?.(new Event("start") as SpeechSynthesisEvent);
    utterance.onboundary?.({ name: "word", charIndex: 9, elapsedTime: 0.3 } as SpeechSynthesisEvent);
    expect(utterance.voice?.localService).toBe(true);
    expect(s.callbacks.boundary).toHaveBeenCalledWith(9, 300);
    cancel(); late?.call(utterance, { name: "word", charIndex: 12, elapsedTime: 1 } as SpeechSynthesisEvent);
    expect(s.callbacks.boundary).toHaveBeenCalledOnce(); expect(utterance.onend).toBeNull();
    expect(s.synthesis.cancel).toHaveBeenCalledTimes(2);
  });
  it("cleans timers and handlers on synthesiser failure and unsubscribes voice discovery", () => {
    const s = setup(), listener = vi.fn(), unsubscribe = s.adapter.subscribe(listener);
    s.adapter.speak("Accepted text.", s.callbacks);
    s.utterance().onstart?.(new Event("start") as SpeechSynthesisEvent);
    s.utterance().onerror?.(new Event("error") as SpeechSynthesisErrorEvent);
    expect(s.callbacks.error).toHaveBeenCalledOnce(); expect(s.utterance().onstart).toBeNull();
    unsubscribe(); expect(s.synthesis.removeEventListener).toHaveBeenCalledWith("voiceschanged", listener);
  });
});

it("selects only installed English voices and applies the configured rate", () => {
  let utterance!: SpeechSynthesisUtterance;
  const voices = [{ voiceURI: "local-a", name: "A", lang: "en-GB", localService: true },
    { voiceURI: "network", name: "Network", lang: "en-US", localService: false },
    { voiceURI: "local-b", name: "B", lang: "en-US", localService: true }];
  const synthesis = { getVoices: () => voices, speak: vi.fn(), cancel: vi.fn() };
  const local = new BrowserLocalSpeech(synthesis as unknown as SpeechSynthesis, (text) => {
    utterance = { text } as SpeechSynthesisUtterance; return utterance;
  });
  expect(local.voices().map((v) => v.id)).toEqual(["local-a", "local-b"]);
  local.configure(1.5, "local-b"); local.speak("Accepted words", { start() {}, boundary() {}, end() {}, error() {} });
  expect(utterance.voice?.voiceURI).toBe("local-b"); expect(utterance.rate).toBe(1.5);
  local.configure(0.75, "network"); local.speak("Accepted words", { start() {}, boundary() {}, end() {}, error() {} });
  expect(utterance.voice?.localService).toBe(true); expect(utterance.rate).toBe(0.75);
});
