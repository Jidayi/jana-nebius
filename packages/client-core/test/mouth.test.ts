// DSN-27 (D103): the presence's speaking mouth follows the loudness of the audio played, within 100 ms of a level
// crossing a threshold, and never changes faster than the hysteresis allows. It reads one loudness number per 20 ms
// frame, so it works with any voice.
import { describe, expect, test, vi } from "vitest";
import { FRAME_MS, MOUTH_SETTINGS, MouthFollower, PLAYBACK_RATE, frameLevels, type MouthShape } from "../src/mouth.js";
import { VoiceController, type VoiceAudio, type VoiceSocket } from "../src/voice.js";

const ORDER: MouthShape[] = ["closed", "small", "medium", "open"];

/** A seeded speech-like recording: syllables of varying loudness with short pauses, PCM16 at 24 kHz. */
function recording(seed = 20261027, seconds = 6): Int16Array {
  let state = seed;
  const random = () => ((state = (state * 1103515245 + 12345) % 2147483648) / 2147483648);
  const pcm = new Int16Array(PLAYBACK_RATE * seconds);
  let at = 0;
  while (at < pcm.length) {
    const syllable = Math.floor(PLAYBACK_RATE * (0.12 + random() * 0.25));
    const pause = Math.floor(PLAYBACK_RATE * random() * 0.15);
    const amplitude = 32767 * 10 ** (-(random() * 40) / 20); // 0 to -40 dBFS
    for (let i = 0; i < syllable && at + i < pcm.length; i++) {
      const envelope = Math.sin((Math.PI * i) / syllable);
      pcm[at + i] = Math.round(amplitude * envelope * Math.sin((2 * Math.PI * 180 * i) / PLAYBACK_RATE));
    }
    at += syllable + pause;
  }
  return pcm;
}

describe("DSN-27", () => {
  test("dsn27_mouth_follows_loudness", () => {
    const levels = frameLevels(recording());
    const follower = new MouthFollower();
    const shapes: MouthShape[] = [];
    const envelopes: number[] = [];
    for (const level of levels) {
      shapes.push(follower.update(level, FRAME_MS));
      envelopes.push(follower.level);
    }
    const [small, medium, open] = MOUTH_SETTINGS.thresholds;
    const thresholds = [small, medium, open];
    expect(new Set(shapes).size).toBeGreaterThanOrEqual(3); // the recording exercises the shapes
    // Within 100 ms of the level crossing a threshold and staying past it, the mouth is at least that open (or, after
    // falling below it by the hysteresis, at most the shape below).
    const within = Math.ceil(100 / FRAME_MS);
    for (let i = 1; i + within < levels.length; i++) {
      thresholds.forEach((threshold, t) => {
        const rose = (levels[i - 1] ?? 0) < threshold && levels.slice(i, i + within + 1).every((l) => l >= threshold);
        if (rose) expect(ORDER.indexOf(shapes[i + within] ?? "closed"), `frame ${i}`).toBeGreaterThanOrEqual(t + 1);
        const low = threshold - MOUTH_SETTINGS.hysteresis;
        const fell = (levels[i - 1] ?? 0) >= low && levels.slice(i, i + within + 1).every((l) => l < low);
        if (fell) expect(ORDER.indexOf(shapes[i + within] ?? "open"), `frame ${i}`).toBeLessThanOrEqual(t);
      });
    }
    // Never faster than the hysteresis allows: a step up passes the threshold, a step down falls below it by the
    // hysteresis, so the mouth never flickers on a level that hovers at a threshold.
    for (let i = 1; i < shapes.length; i++) {
      const before = ORDER.indexOf(shapes[i - 1] ?? "closed"), after = ORDER.indexOf(shapes[i] ?? "closed");
      if (after > before) expect(envelopes[i]).toBeGreaterThanOrEqual(thresholds[after - 1] ?? 0);
      if (after < before) expect(envelopes[i]).toBeLessThan((thresholds[before - 1] ?? 1) - MOUTH_SETTINGS.hysteresis);
    }
    const hovering = new MouthFollower();
    const changes = Array.from({ length: 50 }, (_, i) => hovering.update(small + (i % 2 === 0 ? 0.02 : -0.02), FRAME_MS))
      .filter((shape, i, all) => i > 0 && shape !== all[i - 1]).length;
    expect(changes).toBeLessThanOrEqual(1);
  });

  test("test_dsn27_controller_mouth_from_played_audio", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    let socket: (VoiceSocket & { onmessage: ((event: { data: unknown }) => void) | null }) | undefined;
    let heard = 0;
    const audio: VoiceAudio = { activate: vi.fn(), capture: vi.fn(async () => ({ echoCancellation: true, headphones: false })),
      releaseMic: vi.fn(), play: vi.fn(), flush: vi.fn(), close: vi.fn(), position: () => heard };
    const controller = new VoiceController("ses_mouth", async () => ({ baseUrl: "http://127.0.0.1", token: "t", headers: {} }), audio,
      () => {
        const created = { binaryType: "blob" as BinaryType, readyState: 0, bufferedAmount: 0, onopen: null as (() => void) | null,
          onclose: null, onerror: null, onmessage: null, send: vi.fn(), close: vi.fn() };
        queueMicrotask(() => { created.readyState = 1; created.onopen?.(); });
        socket = created;
        return created;
      });
    await controller.open();
    // 200 ms of loud audio, then 200 ms of silence, under one response tag.
    const pcm = new Int16Array(PLAYBACK_RATE * 0.4);
    for (let i = 0; i < PLAYBACK_RATE * 0.2; i++) pcm[i] = Math.round(30000 * Math.sin((2 * Math.PI * 200 * i) / PLAYBACK_RATE));
    const frame = new Uint8Array(16 + pcm.byteLength);
    frame.set(new Uint8Array(pcm.buffer), 16);
    socket?.onmessage?.({ data: frame.buffer });
    await vi.waitFor(() => expect(audio.play).toHaveBeenCalledOnce());
    heard = 100;
    vi.advanceTimersByTime(100);
    expect(controller.getState().mouth).toBe("open");
    heard = 380;
    vi.advanceTimersByTime(200);
    expect(controller.getState().mouth).toBe("closed");
    controller.close();
    vi.useRealTimers();
  });
});
