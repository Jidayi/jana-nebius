// UIA-03: the delta queue's adaptive flush, under a simulated clock.
import { describe, expect, test } from "vitest";
import { DeltaQueue, type Clock, type Envelope } from "../src/queue.js";

class SimClock implements Clock {
  t = 0;
  private timers: { at: number; fn: () => void; id: number }[] = [];
  private next = 1;
  now = (): number => this.t;
  setTimeout = (fn: () => void, ms: number): unknown => {
    const id = this.next++;
    this.timers.push({ at: this.t + ms, fn, id });
    return id;
  };
  clearTimeout = (handle: unknown): void => {
    this.timers = this.timers.filter((t) => t.id !== handle);
  };
  nextTimer(): number {
    return this.timers.reduce((min, t) => Math.min(min, t.at), Infinity);
  }
  fireDue(): void {
    const due = this.timers.filter((t) => t.at <= this.t).sort((a, b) => a.at - b.at);
    this.timers = this.timers.filter((t) => t.at > this.t);
    for (const t of due) t.fn();
  }
}

function delta(seq: number, part: string): Envelope {
  return { v: 1, channel: "session", seq, epoch: "ep_sim", session_id: "ses_x", turn_id: "trn_x", ts: seq, event: { type: "text.delta", part_id: part, delta: "x" } };
}

describe("UIA-03", () => {
  test("uia03_adaptive_flush", () => {
    const clock = new SimClock();
    const commits: number[] = [];
    let queued = 0;
    let maxQueued = 0;
    const queue = new DeltaQueue(
      (batch) => {
        commits.push(clock.t);
        queued -= batch.length > 0 ? queuedAtFlush : 0;
        clock.t += 30; // a 30 ms render cost per commit
      },
      { clock },
    );
    let queuedAtFlush = 0;
    const originalFlush = queue.flush.bind(queue);
    queue.flush = () => {
      queuedAtFlush = queued;
      originalFlush();
    };
    // 200 events per second for 10 s, alternating two parts so coalescing cannot hide the load.
    const arrivals = Array.from({ length: 2000 }, (_, i) => i * 5);
    let i = 0;
    while (i < arrivals.length || clock.nextTimer() !== Infinity) {
      const nextArrival = arrivals[i] ?? Infinity;
      const nextTimer = clock.nextTimer();
      if (nextArrival <= nextTimer) {
        clock.t = Math.max(clock.t, nextArrival);
        queue.push(delta(i + 1, i % 2 === 0 ? "prt_a" : "prt_b"));
        queued += 1;
        maxQueued = Math.max(maxQueued, queued);
        i += 1;
      } else {
        clock.t = Math.max(clock.t, nextTimer);
        clock.fireDue();
      }
    }
    queue.flush();
    for (let k = 1; k < commits.length; k += 1) expect(commits[k]! - commits[k - 1]!).toBeGreaterThanOrEqual(33);
    expect(maxQueued).toBeLessThanOrEqual(400); // never more than 2 s of events at 200 events/s
    expect(queue.interval).toBeGreaterThan(33); // slow commits widened the interval
  });

  test("events that need the student flush at once", () => {
    const clock = new SimClock();
    const batches: Envelope[][] = [];
    const queue = new DeltaQueue((b) => batches.push(b), { clock });
    queue.push(delta(1, "prt_a"));
    expect(batches).toHaveLength(0);
    queue.push({ ...delta(2, "prt_a"), event: { type: "turn.end", status: "complete" } });
    expect(batches).toHaveLength(1);
    expect(batches[0]!.map((e) => e.event.type)).toEqual(["text.delta", "turn.end"]);
  });
});
