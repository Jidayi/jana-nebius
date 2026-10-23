// UIA-28 (reducer properties), UIA-04 (coalescing equivalence and reset protection), API-08 (part lifecycle).
import { describe, expect, test } from "vitest";
import { coalesce, type Envelope } from "../src/queue.js";
import { reduce } from "../src/reducer.js";
import { emptyStore, type Store } from "../src/store.js";
import { EPOCH, SESSION, prng, sequence } from "./generate.js";

function start(): Store {
  const store = emptyStore();
  return {
    ...store,
    sessions: { [SESSION]: { session_id: SESSION, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false, turn_ids: [], board_ids: [], hint_rung: 0, pending_ids: [] } },
    cursors: { [SESSION]: { epoch: EPOCH, seq: 0 } },
  };
}

const fold = (store: Store, envelopes: Envelope[]): Store => envelopes.reduce(reduce, store);

function batches(random: () => number, envelopes: Envelope[]): Envelope[][] {
  const out: Envelope[][] = [];
  let i = 0;
  while (i < envelopes.length) {
    const size = 1 + Math.floor(random() * 12);
    out.push(envelopes.slice(i, i + size));
    i += size;
  }
  return out;
}

describe("UIA-28", () => {
  test("uia28_reducer_properties", () => {
    for (let n = 0; n < 10_000; n += 1) {
      const random = prng(n + 1);
      const events = sequence(random, 2);
      const once = fold(start(), events);
      // Idempotent: replaying any prefix again changes nothing.
      expect(fold(once, events.slice(0, Math.floor(random() * events.length)))).toBe(once);
      // Out of order: a stale envelope interleaved anywhere is ignored.
      const cut = 1 + Math.floor(random() * (events.length - 1));
      const stale = events[Math.floor(random() * cut)]!;
      const withStale = fold(fold(start(), events.slice(0, cut)).valueOf() as Store, [stale, ...events.slice(cut)]);
      expect(withStale).toEqual(once);
      // Another epoch: the snapshot path is flagged and nothing is applied.
      const foreign = { ...events[0]!, epoch: "ep_other", seq: 10_000 };
      const flagged = reduce({ ...once, connection: {} }, foreign);
      expect(flagged.connection[`session:${SESSION}`]?.resync).toBe(true);
      expect(flagged.parts).toBe(once.parts);
      // Coalescing (UIA-04): reducing coalesced batches equals reducing the raw stream.
      const coalesced = batches(random, events).reduce((s, batch) => fold(s, coalesce(batch)), start());
      expect(coalesced).toEqual(once);
      // Part lifecycle (API-08): an ended part's text never changes; every part is settled after turn.end.
      for (const part of Object.values(once.parts)) {
        expect(["started", "streaming"]).not.toContain(part.status);
        expect(part.tail).toBe("");
      }
    }
  });
});

describe("UIA-04", () => {
  test("uia04_coalescing_equivalent", () => {
    for (let n = 0; n < 2_000; n += 1) {
      const random = prng(50_000 + n);
      const events = sequence(random);
      const raw = fold(start(), events);
      expect(fold(start(), coalesce(events))).toEqual(raw);
      expect(coalesce(events).length).toBeLessThanOrEqual(events.length);
    }
  });

  test("uia04_reset_preserves_accepted_text", () => {
    const partId = "prt_01J00000000000000000000001";
    const turnId = "trn_01J00000000000000000000001";
    const env = (seq: number, event: Record<string, unknown> & { type: string }): Envelope => ({ v: 1, channel: "session", seq, epoch: EPOCH, session_id: SESSION, turn_id: turnId, ts: seq, event });
    const opened = fold(start(), [
      env(1, { type: "turn.start", turn_id: turnId, user_message_id: null, client_message_id: null, intent: "ask", mode: "guided", fork: false }),
      env(2, { type: "part.start", part_id: partId, kind: "text", index: 0 }),
    ]);
    // Resetting an empty placeholder succeeds.
    expect(fold(opened, [env(3, { type: "text.reset", part_id: partId, reason: "regenerating" })]).parts[partId]?.text).toBe("");
    // A reset after a rendered delta cannot clear it.
    const rendered = fold(opened, [env(3, { type: "text.delta", part_id: partId, delta: "Accepted text" })]);
    expect(fold(rendered, [env(4, { type: "text.reset", part_id: partId, reason: "regenerating" })]).parts[partId]?.text).toBe("Accepted text");
    // A reset arriving while the delta is still queued is dropped by the queue, so the text survives the flush.
    const committed: Envelope[][] = [];
    const clock = { now: () => 0, setTimeout: () => 1, clearTimeout: () => undefined };
    return import("../src/queue.js").then(({ DeltaQueue }) => {
      const queue = new DeltaQueue((batch) => committed.push(batch), { clock });
      queue.push(env(3, { type: "text.delta", part_id: partId, delta: "Accepted text" }));
      queue.push(env(4, { type: "text.reset", part_id: partId, reason: "regenerating" }));
      queue.flush();
      const after = fold(opened, committed.flat());
      expect(after.parts[partId]?.text).toBe("Accepted text");
    });
  });
});
