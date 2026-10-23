// API-20 (reconnect), UIA-05 (optimistic and retry), UIA-07 (banner threshold) and UIA-22 (server clock) for the
// stream client and session controller, against a fake core serving a recorded session.
import { describe, expect, test } from "vitest";
import { hydrate } from "../src/hydrate.js";
import { SessionController, StoreHolder } from "../src/session.js";
import { elapsedMs, emptyStore, type Store } from "../src/store.js";
import { StreamClient } from "../src/stream/client.js";
import { FakeCore } from "./fakecore.js";
import { recordings } from "./recordings.js";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function data(store: Store) {
  const { connection: _c, cursors: _k, ...rest } = store;
  return rest;
}

async function until(check: () => boolean, timeoutMs = 10_000): Promise<void> {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error("timed out");
    await sleep(5);
  }
}

function controller(core: FakeCore): SessionController {
  return new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: core.token }) }, new StoreHolder(), core.recording.session_id, { fetch: core.fetch });
}

const recording = recordings().find((r) => r.name === "s1_guided_solve")!;
const finalData = data(hydrate(emptyStore(), recording.snapshots[recording.snapshots.length - 1]!));

describe("API-20", () => {
  test("backoff is exponential with full jitter and capped", () => {
    const client = new StreamClient({ sessionId: "s", endpoint: async () => ({ baseUrl: "", token: "" }), cursor: () => null, onEnvelope: () => {}, resync: async () => {}, onState: () => {}, random: () => 0.999 });
    expect([0, 1, 2, 3, 4, 5, 9].map((a) => client.delay(a))).toEqual([249, 499, 999, 1998, 3996, 4995, 4995]);
    const low = new StreamClient({ sessionId: "s", endpoint: async () => ({ baseUrl: "", token: "" }), cursor: () => null, onEnvelope: () => {}, resync: async () => {}, onState: () => {}, random: () => 0 });
    expect(low.delay(7)).toBe(0);
  });

  test("api20_reconnect_storm", async () => {
    const core = new FakeCore(recording, 25);
    const session = controller(core);
    await session.open();
    core.start();
    const reconnects: number[] = [];
    for (let kill = 0; kill < 20; kill += 1) {
      await sleep(10 + (kill % 3) * 15);
      core.kill();
      const killedAt = Date.now();
      await sleep(20);
      core.restart();
      await until(() => session.holder.getState().connection[`session:${recording.session_id}`]?.state === "live", 6_000);
      reconnects.push(Date.now() - killedAt);
    }
    await until(() => core.done);
    await until(() => JSON.stringify(data(session.holder.getState())) === JSON.stringify(finalData), 6_000).catch(() => undefined);
    session.close();
    core.stop();
    expect(Math.max(...reconnects)).toBeLessThan(6_000);
    const state = session.holder.getState();
    expect(data(state)).toEqual(finalData); // no duplicate or missing parts after 20 restarts
    for (const turn of Object.values(state.turns)) expect(new Set(turn.part_ids).size).toBe(turn.part_ids.length);
  }, 60_000);
});

describe("UIA-07", () => {
  test("uia07_banner_threshold", async () => {
    const core = new FakeCore(recording, 50);
    const session = controller(core);
    await session.open();
    core.start();
    const key = `session:${recording.session_id}`;
    const banners: boolean[] = [];
    session.holder.subscribe(() => banners.push(session.holder.getState().connection[key]?.banner ?? false));
    // A short outage (well under the threshold): reconnects silently.
    await sleep(60);
    core.kill();
    await sleep(300);
    core.restart();
    await until(() => session.holder.getState().connection[key]?.state === "live");
    expect(banners.some(Boolean)).toBe(false);
    // A long outage: the banner appears after the threshold and goes when the stream is live again.
    core.kill();
    await sleep(2_400);
    expect(session.holder.getState().connection[key]?.banner).toBe(true);
    core.restart();
    await until(() => session.holder.getState().connection[key]?.state === "live", 6_000);
    await until(() => session.holder.getState().connection[key]?.banner === false);
    await until(() => core.done);
    await sleep(100);
    session.close();
    core.stop();
    const state = session.holder.getState();
    for (const turn of Object.values(state.turns)) expect(new Set(turn.part_ids).size).toBe(turn.part_ids.length);
  }, 20_000);
});

describe("UIA-05", () => {
  test("uia05_retry_no_duplicate", async () => {
    const core = new FakeCore(recording, 1_000_000);
    const session = controller(core);
    await session.open();
    core.kill(); // the core is restarting when the student presses Enter
    const id = session.send([{ type: "text", text: "s = 10 m" }]);
    const bubble = session.holder.getState().messages[id];
    expect(bubble?.state).toBe("sending"); // shown at once, keyed by its client id
    await sleep(50);
    core.restart();
    await until(() => core.turnStarts === 1, 6_000);
    session.retry(id); // a student pressing "Try again" as well never starts a second turn
    await sleep(100);
    session.close();
    core.stop();
    expect(core.turnStarts).toBe(1);
    expect(session.holder.getState().messages[id]).toBeDefined();
  }, 20_000);
});

describe("UIA-22", () => {
  test("uia22_clock_from_server_time", async () => {
    const core = new FakeCore(recording, 5);
    core.serverOffsetMs = 90_000; // the server's clock runs 90 s ahead of this machine
    const session = controller(core);
    await session.open();
    core.start();
    await until(() => core.position > 10);
    core.kill();
    await sleep(50);
    core.restart();
    const key = `session:${recording.session_id}`;
    await until(() => session.holder.getState().connection[key]?.state === "live");
    await until(() => core.position > 20);
    await sleep(50);
    const connection = session.holder.getState().connection[key];
    session.close();
    core.stop();
    // A phase that started 4 s ago in server time reads 4 s here, within 1 s, after the reconnect.
    const phaseStarted = Date.now() + 90_000 - 4_000;
    expect(Math.abs(elapsedMs(phaseStarted, connection) - 4_000)).toBeLessThan(1_000);
  }, 20_000);
});
