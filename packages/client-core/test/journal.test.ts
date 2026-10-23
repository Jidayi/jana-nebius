import { expect, test, vi } from "vitest";
import { SessionController, StoreHolder } from "../src/session.js";
import { FakeCore } from "./fakecore.js";
import { recordings } from "./recordings.js";

const recording = recordings().find((r) => r.name === "s1_guided_solve")!;

test("live session commits persist a throttled profile journal without browser storage", async () => {
  const core = new FakeCore(recording, 2); const bodies: { snapshot: unknown; envelopes: unknown[] }[] = [];
  const times: number[] = [];
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: core.token }) }, new StoreHolder(), recording.session_id, { fetch: async (url, init) => {
    if (String(url).endsWith("/journal")) {
      if (init?.method === "PUT") { bodies.push(JSON.parse(String(init.body))); times.push(performance.now()); }
      return Response.json(bodies.at(-1) ?? { snapshot: null, envelopes: [] });
    }
    return core.fetch(url, init);
  } });
  try {
    await session.open(); core.start();
    await vi.waitFor(() => expect(core.done).toBe(true), { timeout: 2000 });
    await vi.waitFor(() => expect(bodies.length).toBeGreaterThan(0), { timeout: 1500 });
    expect(JSON.stringify(bodies.at(-1))).toContain("session_id");
    expect(JSON.stringify(bodies)).not.toContain('"connection"');
    for (let i = 1; i < times.length; i++) expect(times[i]! - times[i - 1]!).toBeGreaterThanOrEqual(490);
  } finally { session.close(); core.stop(); }
});

test.each(["snapshot", "closed"])("a late journal cannot overwrite %s state", async (state) => {
  const core = new FakeCore(recording); core.position = Math.floor(recording.frames.length / 2);
  const cache = { snapshot: core.snapshot(), envelopes: [] }; core.position = 0;
  let release!: () => void; const held = new Promise<void>((resolve) => { release = resolve; });
  const holder = new StoreHolder();
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: core.token }) }, holder, recording.session_id, { fetch: async (url, init) => {
    if (String(url).endsWith("/journal")) { await held; return Response.json(cache); }
    return core.fetch(url, init);
  } });
  try {
    await session.open(); if (state === "closed") session.close();
    const data = () => { const { connection: _connection, ...rest } = holder.getState(); return JSON.stringify(rest); };
    const before = data(); release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(data()).toBe(before);
  } finally { release(); session.close(); core.stop(); }
});
