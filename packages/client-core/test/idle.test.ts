// LRN-20's idle trigger, the client's half (API 1.10, D104): one report per open step after `offer_idle_s` with no
// input and the window focused all that time; a new step, input or a lost focus starts the count again.
import { describe, expect, it } from "vitest";
import { errors } from "@jana/contracts-ts";
import { CLIENT_KEYS } from "../src/generated/keys.js";
import { StepIdleWatch, openStepOf, reportStepIdle, type IdleTimers } from "../src/idle.js";
import { emptyStore, type Store } from "../src/store.js";
import type { CommandClient } from "../src/stream/commands.js";

function clock(): IdleTimers & { advance(ms: number): void } {
  let now = 0;
  let next = 1;
  const due = new Map<number, { at: number; run: () => void }>();
  return {
    now: () => now,
    set: (run, ms) => { const id = next++; due.set(id, { at: now + ms, run }); return id; },
    clear: (id) => { due.delete(id as number); },
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...due].sort((a, b) => a[1].at - b[1].at)) {
        if (timer.at <= now) { due.delete(id); timer.run(); }
      }
    },
  };
}

const THRESHOLD = CLIENT_KEYS.offer_idle_s * 1000;

describe("the idle report (LRN-20, D104)", () => {
  it("reports a focused, untouched step once, after the configured idle time", () => {
    const timers = clock();
    const sent: [number, boolean][] = [];
    const watch = new StepIdleWatch((ms, focused) => sent.push([ms, focused]), true, THRESHOLD, timers);
    watch.step("brd_1:stp_1");
    timers.advance(THRESHOLD - 1);
    expect(sent).toEqual([]);
    timers.advance(1);
    expect(sent).toEqual([[THRESHOLD, true]]);
    timers.advance(THRESHOLD * 3);
    expect(sent).toHaveLength(1);
    watch.input();
    timers.advance(THRESHOLD);
    expect(sent).toHaveLength(1);
    watch.step("brd_1:stp_2");
    timers.advance(THRESHOLD);
    expect(sent).toHaveLength(2);
  });

  it("restarts on input and counts only time with the window focused", () => {
    const timers = clock();
    const sent: number[] = [];
    const watch = new StepIdleWatch((ms) => sent.push(ms), true, THRESHOLD, timers);
    watch.step("brd_1:stp_1");
    timers.advance(THRESHOLD - 10);
    watch.input();
    timers.advance(THRESHOLD - 10);
    watch.focus(false);
    timers.advance(THRESHOLD * 2);
    expect(sent).toEqual([]);
    watch.focus(true);
    timers.advance(THRESHOLD);
    expect(sent).toEqual([THRESHOLD]);
    watch.step(null);
    watch.close();
  });

  it("finds the open step only while a problem is on the board and no turn runs", () => {
    const store: Store = emptyStore();
    expect(openStepOf(store, "ses_1")).toBeNull();
    store.sessions["ses_1"] = { session_id: "ses_1", title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0,
      archived: false, turn_ids: ["trn_1"], board_ids: ["brd_1"], hint_rung: 0, pending_ids: [] };
    store.boards["brd_1"] = { board_id: "brd_1", part_id: null, problem: { text: "A trolley", latex: null }, step_ids: ["stp_1"], steps: {}, knowns: [],
      unknowns: [], conventions: [], await: { step_id: "stp_2", prompt: "Your turn", input_kind: "maths" }, highlight: null, current: "stp_1" };
    store.turns["trn_1"] = { status: "streaming" } as Store["turns"][string];
    expect(openStepOf(store, "ses_1")).toBeNull();
    store.turns["trn_1"] = { status: "complete" } as Store["turns"][string];
    expect(openStepOf(store, "ses_1")).toBe("brd_1:stp_2");
  });

  it("sends a StepIdle body and drops a refusal", async () => {
    const posted: [string, unknown][] = [];
    const commands = { post: async (path: string, body: unknown) => { posted.push([path, body]); throw new Error("turn_active"); } } as unknown as CommandClient;
    await reportStepIdle(commands, "ses_1", THRESHOLD + 0.4, true);
    expect(posted).toEqual([["/v1/sessions/ses_1/idle", { idle_ms: THRESHOLD, focused: true }]]);
    expect(errors("api/commands#/$defs/StepIdle", posted[0]?.[1])).toEqual([]);
  });
});
