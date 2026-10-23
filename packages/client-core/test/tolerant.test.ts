// API-35: the tolerant reader lets a 1.0 client read a newer core of the same major.
import { describe, expect, test } from "vitest";
import { emptyStore, readEnvelope, reduce, UNKNOWN, type Store } from "../src/index.js";
import type { Envelope } from "../src/queue.js";
import { recordings } from "./recordings.js";

function readAll(frames: unknown[]): { store: Store; skipped: string[]; rejected: string[][] } {
  let store = emptyStore();
  const skipped: string[] = [];
  const rejected: string[][] = [];
  for (const frame of frames) {
    const read = readEnvelope(frame);
    if (read.kind === "accept") store = reduce(store, read.envelope as unknown as Envelope);
    else if (read.kind === "skip") skipped.push(read.type);
    else rejected.push(read.errors);
  }
  return { store, skipped, rejected };
}

describe("API-35", () => {
  test("api35_tolerant_reader_rules", () => {
    const original = recordings()[0]!.frames;
    const plain = readAll(original);
    expect(plain.skipped).toEqual([]);
    expect(plain.rejected).toEqual([]);

    // A newer core: an unknown envelope field everywhere, an unknown event type, and an unknown status phase.
    const statusAt = original.findIndex((f) => f.event.type === "status");
    expect(statusAt).toBeGreaterThanOrEqual(0);
    const newer: unknown[] = original.map((f) => ({ ...f, trace_ref: "trc_from_a_newer_core" }));
    const status = newer[statusAt] as Envelope;
    newer[statusAt] = { ...status, event: { ...status.event, phase: "planning_v2", extra_detail: 3 } };
    newer.splice(statusAt + 1, 0, { ...status, seq: status.seq, event: { type: "hint.glow", level: 2 } });
    const read = readAll(newer);
    expect(read.rejected).toEqual([]);
    expect(read.skipped).toEqual(["hint.glow"]);
    // The turn renders as before; the unknown phase is held as `unknown`, which the status line labels generically.
    const strip = (s: Store) => JSON.stringify({ ...s, turns: Object.keys(s.turns), parts: s.parts, messages: s.messages });
    expect(strip(read.store)).toEqual(strip(plain.store));
    const accepted = readEnvelope(newer[statusAt]);
    expect(accepted.kind).toBe("accept");
    if (accepted.kind === "accept") {
      expect((accepted.envelope.event as { phase?: string }).phase).toBe(UNKNOWN);
      expect("extra_detail" in accepted.envelope.event).toBe(false);
      expect("trace_ref" in accepted.envelope).toBe(false);
      expect(accepted.unknown).toEqual(["$.event.phase=planning_v2"]);
    }

    // What remains is validated strictly: an event missing a required field is rejected.
    const part = original.find((f) => f.event.type === "part.start")!;
    const { kind: _dropped, ...withoutKind } = part.event as Record<string, unknown>;
    expect(readEnvelope({ ...part, event: withoutKind }).kind).toBe("reject");
    const { seq: _seq, ...withoutSeq } = part as unknown as Record<string, unknown>;
    expect(readEnvelope(withoutSeq).kind).toBe("reject");
  });
});
