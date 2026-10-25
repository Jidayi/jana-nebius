import { afterEach, expect, test, vi } from "vitest";
import { BrowserPodcastAudio } from "../src/podcast-audio.js";

afterEach(() => vi.unstubAllGlobals());

function context(decode: Promise<unknown>) {
  const node = { buffer: null, playbackRate: { value: 1 }, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null as (() => void) | null };
  const value = { suspend: vi.fn(async () => {}), resume: vi.fn(async () => {}), destination: {}, decodeAudioData: vi.fn(() => decode), createBufferSource: () => node };
  vi.stubGlobal("AudioContext", function AudioContextStub() { return value; });
  return { node, value };
}

test("decoded NVIDIA audio plays at the existing speech rate and Stop releases the playback node", async () => {
  const { node } = context(Promise.resolve({ duration: 4, numberOfChannels: 1 }));
  const player = new BrowserPodcastAudio(), callbacks = { end: vi.fn(), error: vi.fn() };
  player.activate();
  const stop = player.play(new Blob([new Uint8Array(52)], { type: "audio/wav" }), 1.2, callbacks);
  await vi.waitFor(() => expect(node.start).toHaveBeenCalledOnce());
  expect(node.playbackRate.value).toBe(1.2);
  stop();
  expect(node.stop).toHaveBeenCalledOnce();
  expect(node.disconnect).toHaveBeenCalledOnce();
  expect(callbacks.end).not.toHaveBeenCalled();
});

test("Stop during decoding prevents late audio from ever starting", async () => {
  let decoded: ((value: unknown) => void) | undefined;
  const { node } = context(new Promise((resolve) => { decoded = resolve; }));
  const player = new BrowserPodcastAudio(), callbacks = { end: vi.fn(), error: vi.fn() };
  const stop = player.play(new Blob([new Uint8Array(52)], { type: "audio/wav" }), 1, callbacks);
  stop();
  decoded!({ duration: 2, numberOfChannels: 1 });
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  expect(node.start).not.toHaveBeenCalled();
  expect(callbacks.end).not.toHaveBeenCalled();
});

test("an invalid decoded duration is refused instead of playing unbounded audio", async () => {
  const { node } = context(Promise.resolve({ duration: 1000, numberOfChannels: 1 }));
  const callbacks = { end: vi.fn(), error: vi.fn() };
  new BrowserPodcastAudio().play(new Blob([new Uint8Array(52)]), 1, callbacks);
  await vi.waitFor(() => expect(callbacks.error).toHaveBeenCalledOnce());
  expect(node.start).not.toHaveBeenCalled();
});

test("Pause and Resume preserve the current decoded playback node", async () => {
  const { node, value } = context(Promise.resolve({ duration: 4, numberOfChannels: 1 }));
  const player = new BrowserPodcastAudio();
  player.play(new Blob([new Uint8Array(52)]), 1, { end: vi.fn(), error: vi.fn() });
  await vi.waitFor(() => expect(node.start).toHaveBeenCalledOnce());
  player.pause(); expect(value.suspend).toHaveBeenCalledOnce();
  player.resume(); expect(value.resume).toHaveBeenCalled();
  expect(node.stop).not.toHaveBeenCalled();
  expect(node.start).toHaveBeenCalledOnce();
});
