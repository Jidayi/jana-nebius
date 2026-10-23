import { runInNewContext } from "node:vm";
import { afterEach, expect, test, vi } from "vitest";
import { BrowserVoiceAudio } from "../src/voice-audio.js";
import workletSource from "../src/voice-capture-worklet.js?raw";

class Source {
  onended: (() => void) | null = null;
  buffer: unknown;
  playbackRate = { value: 1 };
  start = vi.fn();
  stop = vi.fn();
  connect = vi.fn();
  disconnect = vi.fn();
}
class Context {
  static all: Context[] = [];
  currentTime = 0;
  destination = {};
  nodes: Source[] = [];
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);
  constructor() { Context.all.push(this); }
  createBuffer(_channels: number, length: number, rate: number) {
    return { getChannelData: () => new Float32Array(length), duration: length / rate };
  }
  createBufferSource() { const node = new Source(); this.nodes.push(node); return node; }
}
afterEach(() => { vi.unstubAllGlobals(); Context.all.length = 0; });

test("playback position counts rendered samples and excludes buffering gaps", () => {
  vi.stubGlobal("AudioContext", Context);
  const audio = new BrowserVoiceAudio();
  const report = vi.fn();
  audio.play("response", new Int16Array(2400), report);
  const context = Context.all[0]!;
  context.currentTime = 0.12;
  context.nodes[0]!.onended!();
  expect(report).toHaveBeenLastCalledWith(100, true);
  context.currentTime = 0.7; // no audio played during this gap
  audio.play("response", new Int16Array(2400), report);
  context.currentTime = 0.76;
  audio.flush("response");
  const played = report.mock.lastCall![0] as number;
  expect(played).toBeGreaterThanOrEqual(149);
  expect(played).toBeLessThanOrEqual(150);
  expect(report.mock.lastCall![1]).toBe(false);
  expect(context.nodes[1]!.stop).toHaveBeenCalledOnce();
  audio.close();
  expect(context.close).toHaveBeenCalledOnce();
});

test("test_voc52_heard_position_is_less_the_output_latency", () => {
  // VOC-51, VOC-52: the heard position is what the speaker has output (the audio clock less the device's reported
  // latency), so cues and the heard extent never run ahead of the student's ears; nothing is heard before playback.
  vi.stubGlobal("AudioContext", Context);
  const audio = new BrowserVoiceAudio();
  const report = vi.fn();
  audio.play("response", new Int16Array(24000), report); // one second, starting 20 ms from now
  const context = Context.all[0]! as Context & { outputLatency?: number };
  context.outputLatency = 0.05;
  expect(audio.position("response")).toBeNull();
  context.currentTime = 0.05; // the clock has started this audio, the speaker not yet
  expect(audio.position("response")).toBeNull();
  context.currentTime = 0.57;
  const heard = audio.position("response") ?? 0;
  expect(heard).toBeGreaterThanOrEqual(499); // 500 ms heard: 570 ms of clock, less 20 ms of lead-in and 50 ms of latency
  expect(heard).toBeLessThanOrEqual(500);
  audio.flush("response");
  expect(report).toHaveBeenLastCalledWith(heard, false); // the heard extent at the stop, not what was queued
  expect(audio.position("unknown")).toBeNull();
  audio.close();
});

test("flush stops all queued nodes and never counts audio still waiting to play", () => {
  vi.stubGlobal("AudioContext", Context);
  const audio = new BrowserVoiceAudio();
  const report = vi.fn();
  for (let i = 0; i < 5; i++) audio.play("response", new Int16Array(2400), report);
  audio.flush();
  expect(report).toHaveBeenLastCalledWith(0, false);
  for (const source of Context.all[0]!.nodes) {
    expect(source.stop).toHaveBeenCalledOnce();
    expect(source.onended).toBeNull();
  }
  audio.close();
});

test("releasing capture while OS permission is pending closes the granted tracks", async () => {
  vi.stubGlobal("AudioContext", Context);
  let grant!: (stream: unknown) => void;
  const stop = vi.fn();
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn(() => new Promise((resolve) => { grant = resolve; })) } });
  const audio = new BrowserVoiceAudio();
  const capture = audio.capture(vi.fn());
  audio.releaseMic();
  grant({ getTracks: () => [{ stop }] });
  await capture;
  expect(stop).toHaveBeenCalledOnce();
  expect(Context.all).toHaveLength(0);
});

test("a refused or missing microphone keeps its error name for the VOC-16 copy and releases the tracks", async () => {
  vi.stubGlobal("AudioContext", Context);
  for (const name of ["NotFoundError", "NotAllowedError"]) {
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn(async () => { throw Object.assign(new Error(name), { name }); }) } });
    const audio = new BrowserVoiceAudio();
    await expect(audio.capture(vi.fn())).rejects.toMatchObject({ name, message: "voice_microphone_unavailable" });
  }
  expect(Context.all).toHaveLength(0);
});

test.each([16000, 24000, 44100, 48000, 96000])("worklet resamples %i Hz into bounded PCM24k frames", (rate) => {
  const frames: Int16Array[] = [];
  let Processor!: new () => { process(inputs: Float32Array[][]): boolean };
  runInNewContext(workletSource, {
    AudioWorkletProcessor: class { port = { postMessage: (buffer: ArrayBuffer) => frames.push(new Int16Array(buffer)) }; },
    sampleRate: rate,
    registerProcessor: (name: string, constructor: typeof Processor) => {
      expect(name).toBe("jana-voice-capture"); Processor = constructor;
    },
  });
  const processor = new Processor();
  // One second, plus the previous-sample endpoint, in the browser's usual render blocks.
  for (let start = 0; start <= rate; start += 128) {
    const length = Math.min(128, rate + 1 - start);
    const left = new Float32Array(length).fill(0.75);
    const right = new Float32Array(length).fill(-0.25);
    expect(processor.process([[left, right]])).toBe(true);
  }
  expect(frames).toHaveLength(50);
  for (const frame of frames) {
    expect(frame.byteLength).toBe(960);
    expect(frame.every((sample) => sample === 8192)).toBe(true); // mono average is 0.25
  }
});

test("rate changes scheduling while heard-text progress stays in source PCM time", () => {
  vi.stubGlobal("AudioContext", Context);
  const audio = new BrowserVoiceAudio(), report = vi.fn();
  audio.setRate(1.5); audio.play("response", new Int16Array(24000), report);
  const context = Context.all[0]!;
  expect(context.nodes[0]!.playbackRate.value).toBe(1.5);
  context.currentTime = 0.52; audio.flush("response");
  expect(report.mock.lastCall![0]).toBe(750); audio.close();
});
