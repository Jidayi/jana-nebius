// UIA-02, UIA-28 (recorded streams), API-06 and UIA-30 (recorded payloads) for the reducer and hydrate.
import { describe, expect, test, vi } from "vitest";
import { SessionController, StoreHolder } from "../src/session.js";
import { errors } from "@jana/contracts-ts";
import { hydrate } from "../src/hydrate.js";
import { optimistic, reduce } from "../src/reducer.js";
import { emptyStore, type Store } from "../src/store.js";
import { recordings, type Recording } from "./recordings.js";

/** The data slices: the connection slice is the client's own, not a fold of events. */
function data(store: Store): Omit<Store, "connection"> {
  const { connection: _connection, ...rest } = store;
  return rest;
}

/** Apply frames [from, to) to `store`, inserting each send where the client sent it: a send recorded at
 * `after_seq == i` happened after frame i (snapshot i) and before frame i + 1. */
function play(store: Store, recording: Recording, from: number, to: number): Store {
  let next = store;
  for (let i = from; i < to; i += 1) {
    for (const send of recording.sends) {
      if (send.after_seq === i) next = optimistic(next, recording.session_id, send.body.client_message_id, send.body.content);
    }
    next = reduce(next, recording.frames[i]!);
  }
  return next;
}

function replay(recording: Recording, k: number): Store {
  return play(hydrate(emptyStore(), recording.snapshots[0]!), recording, 0, k);
}

describe.each(recordings())("recording $name", (recording) => {
  test("uia02_reducer_idempotent", () => {
    const once = replay(recording, recording.frames.length);
    let twice = once;
    for (const frame of recording.frames) twice = reduce(twice, frame);
    expect(data(twice)).toEqual(data(once));
    expect(twice).toBe(once); // nothing at or below the cursor touches the store
  });

  test("uia02_snapshot_equivalence", () => {
    // hydrate(snapshot at k) then the events after k equals applying the whole stream, for every cut point.
    const whole = replay(recording, recording.frames.length);
    for (let k = 0; k <= recording.frames.length; k += 1) {
      const atK = hydrate(emptyStore(), recording.snapshots[k]!);
      expect(data(atK)).toEqual(data(replay(recording, k)));
      const resumed = play(atK, recording, k, recording.frames.length);
      expect(data(resumed)).toEqual(data(whole));
    }
  });

  test("uia30_payload_contracts", () => {
    for (const frame of recording.frames) expect(errors("api/events", frame)).toEqual([]);
    for (const send of recording.sends) expect(errors("api/commands#/$defs/StartTurn", send.body)).toEqual([]);
    for (const snapshot of recording.snapshots) expect(errors("api/commands#/$defs/Snapshot", snapshot)).toEqual([]);
  });
});

describe("API-06", () => {
  test("api06_unknown_event_ignored", () => {
    const [recording] = recordings();
    const base = replay(recording!, recording!.frames.length);
    const last = recording!.frames[recording!.frames.length - 1]!;
    const future = { ...last, seq: last.seq + 1, event: { type: "future.thing", anything: [1, 2, 3] } };
    const after = reduce(base, future);
    expect(data({ ...after, cursors: base.cursors })).toEqual(data(base)); // only the cursor moves
    const extra = { ...last, seq: last.seq + 2, event: { ...last.event, novel_field: "kept out" } };
    expect(() => reduce(after, extra)).not.toThrow();
    // The client logs one warning per unknown type, however many arrive.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const session = new SessionController({ endpoint: async () => ({ baseUrl: "", token: "" }) }, new StoreHolder(), recording!.session_id);
    const commit = (session as unknown as { commit(batch: unknown[]): void }).commit.bind(session);
    commit([future, { ...future, seq: future.seq + 1 }]);
    commit([{ ...future, seq: future.seq + 2 }]);
    expect(warn.mock.calls.filter((c) => c[0] === "unknown_event_ignored")).toHaveLength(1);
    warn.mockRestore();
    session.close();
  });
});
