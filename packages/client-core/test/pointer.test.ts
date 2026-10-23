// M43.f on the client: speech-linked cues fire from the audio the student hears (VOC-51), the temporary pointer clears
// at once on interruption, a flush, a session change or a revised or removed target (UXS-63), a stopped turn's later
// events never touch the screen (VOC-52), and estimated timing is reported as estimated. The audio clock below is a
// scripted stand-in for the device with a known output latency; real-device timings are measured separately.
import { afterEach, describe, expect, it, test, vi } from "vitest";
import { CLIENT_KEYS } from "../src/generated/keys.js";
import { CueSync, cueReport, parseTarget, wordTime, type CaptionCue, type CaptionWord } from "../src/pointer.js";
import { VoiceController, type VoiceAudio, type VoiceSocket } from "../src/voice.js";

const STEP = "stp_01JZ0000000000000000000001";
const NEW_LINE = "stp_01JZ0000000000000000000002";
const PART = "vis_01JZ0000000000000000000003:refracted_ray";
const TURN = "trn_01JZ0000000000000000000001";
const TEXT = "This line adds three to two x. Two x plus three minus three equals eleven minus three. What next?";
const WORDS: CaptionWord[] = TEXT.split(" ").map((w, i) => ({ w, start_ms: i * 300 }));
const at = (word: string) => TEXT.indexOf(word);
const CUES: CaptionCue[] = [{ char_offset: at("line"), target: STEP },
  { char_offset: at("Two x plus"), target: NEW_LINE, action: "write", end_offset: at(" What") }];

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
}

/** A device whose speaker lags the audio clock by `latency` ms; `heard` is what has reached the student's ears. */
class Device implements VoiceAudio {
  clock = 0;
  started: number | null = null;
  constructor(readonly latency: number) {}
  activate = vi.fn(); releaseMic = vi.fn(); close = vi.fn();
  capture = vi.fn(async () => ({ echoCancellation: true, headphones: false }));
  flush = vi.fn();
  play = vi.fn(() => { this.started ??= this.clock; });
  /** Playback begins only when `start()` is called: before that, audio is received and queued but not playing. */
  playing = false;
  start(): void { this.playing = true; this.started = this.clock; }
  position(): number | null {
    if (!this.playing || this.started === null) return null;
    const heard = this.clock - this.started - this.latency;
    return heard < 0 ? null : heard;
  }
}

async function tagOf(id: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(id)), 0, 16);
}

async function setup(latency = 150) {
  const device = new Device(latency);
  const socket = new Socket();
  const controller = new VoiceController("ses_one", async () => ({ baseUrl: "http://127.0.0.1", token: "t" }), device,
    () => { queueMicrotask(() => { socket.readyState = 1; socket.onopen?.(); }); return socket; });
  await controller.open();
  const tag = await tagOf("resp_1");
  const frame = new Uint8Array(16 + 4800);
  frame.set(tag, 0);
  return { device, socket, controller, receive: () => socket.onmessage?.({ data: frame.buffer.slice(0) }) };
}

function caption(controller: VoiceController, cues = CUES, turnId = TURN) {
  controller.event({ type: "voice.caption", speaker: "tutor", item_id: null, turn_id: turnId, committed_text: TEXT,
    tentative_text: "", words: WORDS, cues, final: false });
}

/** Advance the scripted device and the controller's timer together, returning when each target first showed. */
async function play(device: Device, controller: VoiceController, ms: number): Promise<Map<string, number>> {
  const shown = new Map<string, number>();
  for (let t = 0; t < ms; t += 5) {
    device.clock += 5;
    vi.setSystemTime(device.clock);
    await vi.advanceTimersByTimeAsync(5);
    const pointer = controller.getState().pointer;
    if (pointer !== null) {
      const id = pointer.target.kind === "step" ? pointer.target.step_id : `${pointer.target.visual_id}:${pointer.target.part_id}`;
      if (!shown.has(id)) shown.set(id, device.clock - (device.started ?? 0) - device.latency);
    }
  }
  return shown;
}

afterEach(() => { vi.useRealTimers(); });

describe("M43.f cues on the client", () => {
  test("voc51_cues_follow_playback", async () => {
    const { device, controller, receive } = await setup(150);
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    receive();
    await vi.advanceTimersByTimeAsync(0);
    caption(controller);
    device.start();
    const shown = await play(device, controller, 3000);
    // Each cue fires once its word has been heard (the clock less the output latency), and within the budget.
    for (const cue of CUES) {
      const word = wordTime(TEXT, WORDS, cue.char_offset) ?? -1;
      const heardAt = shown.get(cue.target);
      expect(heardAt).toBeDefined();
      expect(heardAt ?? 0).toBeGreaterThanOrEqual(word);
      expect((heardAt ?? 0) - word).toBeLessThanOrEqual(CLIENT_KEYS.cue_fire_tolerance_ms);
    }
    expect(controller.getState().writing?.step_id).toBe(NEW_LINE);
    controller.close();
  });

  test("voc51_no_cue_before_audio_plays", async () => {
    const { device, controller, receive } = await setup(150);
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    receive();
    receive();
    await vi.advanceTimersByTimeAsync(0);
    caption(controller); // the caption, its cues and the audio have all arrived: none of it has played
    const early = await play(device, controller, 2000);
    expect(early.size).toBe(0);
    expect(controller.getState().pointer).toBeNull();
    device.start(); // now it plays, after a delay: the first cue waits for its word to be heard
    const late = await play(device, controller, 600);
    expect(late.get(STEP) ?? -1).toBeGreaterThanOrEqual(wordTime(TEXT, WORDS, CUES[0]?.char_offset ?? 0) ?? 0);
    controller.close();
  });

  test("test_voc51_a_gap_in_the_audio_fires_nothing_ahead", async () => {
    // The device's queue runs dry between two frames (a network or synthesis gap): its "ended" report says only what
    // has played, so the cues of words not yet received or played still wait.
    const { device, controller, receive } = await setup(0);
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    receive();
    await vi.advanceTimersByTimeAsync(0);
    caption(controller);
    const report = device.play.mock.calls[0]?.[2] as unknown as ((ms: number, ended: boolean) => void) | undefined;
    report?.(400, true); // 400 ms played, then the queue is empty for a moment
    await vi.advanceTimersByTimeAsync(5);
    expect(controller.getState().pointer?.target).toEqual({ kind: "step", step_id: STEP }); // "line" at 300 ms
    expect(controller.cues.records.map((r) => r.target)).toEqual([STEP]); // the write cue at 3.6 s waits
    controller.close();
  });

  test("voc51_estimated_timing_labelled", async () => {
    const { device, controller, receive } = await setup(0);
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    receive();
    await vi.advanceTimersByTimeAsync(0);
    caption(controller);
    device.start();
    await play(device, controller, 3000);
    const records = controller.cues.records;
    expect(records.length).toBe(2);
    expect(records.every((r) => r.timing === "estimated")).toBe(true);
    const report = cueReport(records);
    expect(report.estimated.count).toBe(2);
    expect(report.measured.count).toBe(0); // never presented as measured
    // A source that does report word boundaries is recorded as measured, separately.
    const measured = new CueSync(1000);
    measured.caption(TURN, TEXT, WORDS, CUES, "measured");
    measured.progress(10_000, 0);
    expect(cueReport(measured.records).measured.count).toBe(2);
    controller.close();
  });

  test("uxs63_cleanup_on_interrupt_and_revision", async () => {
    const clears: Record<string, (c: VoiceController, s: Socket) => void | Promise<void>> = {
      flush: async (_c, s) => { s.onmessage?.({ data: JSON.stringify({ type: "flush", response_id: "resp_1" }) }); },
      stop: (c) => { c.stop(); },
      interrupted: (c) => { c.event({ type: "voice.state", state: "interrupted", reason_key: null, turn_id: TURN, listening_variant: null }); },
      barge_in: async (c) => { await c.ptt(true); },
      session_change: (c) => { c.close(); },
      revision: (c) => { c.event({ type: "board.step", step_id: STEP, latex: "2x + 3 = 12" }); },
      removal: (c) => { c.event({ type: "board.reset", board_id: "brd_x" }); },
    };
    for (const [name, clear] of Object.entries(clears)) {
      const { device, controller, socket, receive } = await setup(0);
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
      controller.event({ type: "board.step", step_id: STEP, latex: "2x + 3 = 11" });
      receive();
      await vi.advanceTimersByTimeAsync(0);
      caption(controller);
      device.start();
      await play(device, controller, 700);
      expect(controller.getState().pointer?.target, name).toEqual({ kind: "step", step_id: STEP });
      await clear(controller, socket);
      for (let i = 0; i < 5; i++) await new Promise((resolve) => setTimeout(resolve, 0)); // the flush id digest settles
      await vi.advanceTimersByTimeAsync(5); // within one frame
      expect(controller.getState().pointer, name).toBeNull();
      vi.useRealTimers();
      controller.close();
    }
  });

  test("test_voc52_a_stopped_turn_never_updates_the_screen", async () => {
    const { device, controller, receive } = await setup(0);
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    receive();
    await vi.advanceTimersByTimeAsync(0);
    caption(controller);
    device.start();
    await play(device, controller, 400);
    controller.stop();
    caption(controller); // a late caption of the stopped response
    receive();
    await vi.advanceTimersByTimeAsync(0);
    const after = await play(device, controller, 3000);
    expect(after.size).toBe(0);
    expect(controller.getState().pointer).toBeNull();
    controller.close();
  });
});

describe("cue targets and timing", () => {
  it("test_vsl45_only_exact_ids_are_targets", () => {
    expect(parseTarget(STEP)).toEqual({ kind: "step", step_id: STEP });
    expect(parseTarget(PART)).toEqual({ kind: "part", visual_id: "vis_01JZ0000000000000000000003", part_id: "refracted_ray" });
    for (const bad of ["the second line", "stp_1", "vis_01JZ0000000000000000000003:", "refracted_ray", "line 2"]) {
      expect(parseTarget(bad)).toBeNull();
    }
    const sync = new CueSync(1000);
    sync.caption(TURN, TEXT, WORDS, [{ char_offset: 0, target: "the equation" }], "estimated");
    sync.progress(10_000, 0);
    expect(sync.getState().pointer).toBeNull();
  });

  it("test_voc10_pointer_clears_after_its_time_to_live_or_at_the_next_pointer", () => {
    const sync = new CueSync(CLIENT_KEYS.pointer_ttl_ms);
    sync.caption(TURN, TEXT, WORDS, [{ char_offset: 0, target: STEP }, { char_offset: at("eleven"), target: PART }], "estimated");
    sync.progress(0, 1000);
    expect(sync.getState().pointer?.target.kind).toBe("step");
    sync.progress(wordTime(TEXT, WORDS, at("eleven")) ?? 0, 1500);
    expect(sync.getState().pointer?.target.kind).toBe("part"); // the next pointer replaces it
    sync.tick(1500 + CLIENT_KEYS.pointer_ttl_ms);
    expect(sync.getState().pointer).toBeNull();
  });

  it("test_voc51_write_progress_follows_the_words_that_cite_the_line", () => {
    const sync = new CueSync(1000);
    sync.caption(TURN, TEXT, WORDS, CUES, "estimated");
    const start = wordTime(TEXT, WORDS, at("Two x plus")) ?? 0;
    const end = wordTime(TEXT, WORDS, at("What")) ?? 0;
    sync.progress(start, 0);
    expect(sync.getState().writing).toEqual({ step_id: NEW_LINE, progress: 0, timing: "estimated" });
    sync.progress((start + end) / 2, 10);
    expect(sync.getState().writing?.progress).toBeCloseTo(0.5, 1);
    sync.progress(end, 20);
    expect(sync.getState().writing?.progress).toBe(1);
  });
});
