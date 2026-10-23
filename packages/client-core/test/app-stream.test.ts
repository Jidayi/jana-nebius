import { expect, test, vi } from "vitest";
import { ProfileController, StoreHolder } from "../src/index.js";
import { ulid } from "../src/ids.js";
import type { Envelope } from "../src/queue.js";

test("the app stream is shared, validates and deduplicates events, and resumes without a profile token", async () => {
  const calls: Headers[] = [];
  let aborted = 0;
  const events: Envelope[] = [];
  const fetcher: typeof fetch = async (_url, init) => {
    calls.push(new Headers(init?.headers));
    const body = new ReadableStream<Uint8Array>({ start(controller) {
      const event = (seq: number) => ({ v: 1, channel: "app", seq, epoch: "syntheticapp001", session_id: null,
        turn_id: null, ts: 1800000000000, event: { type: "model.download", download_id: `dl_${ulid(100)}`,
          model_id: "mp.synth.8b.q4_k_m.low", state: "downloading", bytes_done: seq * 10, bytes_total: 100,
          eta_s: 1, error_code: null } });
      for (const seq of [1, 1, 2]) controller.enqueue(new TextEncoder().encode(`event: data\ndata: ${JSON.stringify(event(seq))}\n\n`));
      init?.signal?.addEventListener("abort", () => { aborted += 1; controller.close(); });
    } });
    return new Response(body, { headers: { "content-type": "text/event-stream" } });
  };
  const profiles = new ProfileController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, new StoreHolder(), { fetch: fetcher });
  const off = profiles.onAppEnvelope((event) => events.push(event));
  const first = profiles.watchApp();
  const second = profiles.watchApp();
  try {
    await vi.waitFor(() => expect(events.map((e) => e.seq)).toEqual([1, 2]));
    expect(calls).toHaveLength(1);
    expect(calls[0]?.get("x-profile-token")).toBeNull();
    first();
    expect(aborted).toBe(0);
    second();
    expect(aborted).toBe(1);
    const reopened = profiles.watchApp();
    try {
      await vi.waitFor(() => expect(calls).toHaveLength(2));
      expect(calls[1]?.get("last-event-id")).toBe("syntheticapp001:2");
      expect(events.map((e) => e.seq)).toEqual([1, 2]);
    } finally { reopened(); }
  } finally { first(); second(); off(); }
});
