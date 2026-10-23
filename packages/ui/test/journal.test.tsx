import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { SessionController, StoreHolder, type Envelope } from "@jana/client-core";
import { SessionJournal, journalSnapshot } from "../../client-core/src/journal.js";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { Transcript } from "../src/transcript/Transcript.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION, id, snapshot } from "./harness.js";

afterEach(cleanup);

test("uia06_crash_repaint", async () => {
  let cache: unknown = { snapshot: null, envelopes: [] };
  let writes = 0;
  const f = new Fixture(); const base = snapshot(); const envelopes: Envelope[] = [];
  const start = f.emit.bind(f); f.emit = (...args) => { const event = start(...args); envelopes.push(event); return event; };
  f.startTurn(); const part = id("prt");
  f.emit({ type: "part.start", part_id: part, kind: "text", index: 0 });
  f.emit({ type: "text.delta", part_id: part, delta: "Last seen before the client crash." });
  const journal = new SessionJournal({ put: async (_path: string, body: unknown) => { cache = structuredClone(body); writes++; } } as never, SESSION, () => f.holder.getState());
  journal.fresh(base); journal.append(envelopes);
  await waitFor(() => expect(writes).toBe(1), { timeout: 1000 });
  journal.close(); // Abrupt client loss: a new holder and controller, with no shared client state.
  let release!: () => void; const held = new Promise<void>((resolve) => { release = resolve; });
  const holder = new StoreHolder();
  const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, holder, SESSION, { fetch: async (url, init) => {
    const path = new URL(String(url)).pathname;
    if (path.endsWith("/journal")) { if (init?.method === "PUT") cache = JSON.parse(String(init.body)); return Response.json(cache); }
    if (path.endsWith("/snapshot")) { await held; return Response.json(snapshot()); }
    return new Response(new ReadableStream({ start(controller) { init?.signal?.addEventListener("abort", () => controller.close()); } }), { headers: { "content-type": "text/event-stream" } });
  } });
  render(<LocaleProvider locale="en"><RegistryProvider registry={defaultRegistry()}><StoreProvider holder={holder} session={session}><Transcript sessionId={SESSION} /></StoreProvider></RegistryProvider></LocaleProvider>);
  let opened!: Promise<void>; const started = performance.now();
  await act(async () => { opened = session.open(); });
  await screen.findByText("Last seen before the client crash.", {}, { timeout: 300 });
  expect(performance.now() - started).toBeLessThan(300);
  expect(Object.keys(holder.getState().turns)).toHaveLength(1);
  await act(async () => { release(); await opened; });
  expect(screen.queryByText("Last seen before the client crash.")).toBeNull();
  expect(holder.getState().sessions[SESSION]?.turn_ids).toEqual([]); // authoritative empty snapshot wins
  session.close();
});

test("journal compaction bounds the transcript tail and excludes credentials and unrelated sessions", () => {
  const f = new Fixture();
  for (let index = 0; index < 60; index++) { f.startTurn(); f.text(`Line ${index}`); f.end(); }
  const cached = journalSnapshot(f.holder.getState(), SESSION)!;
  expect(cached.messages).toHaveLength(50);
  expect(Object.keys(cached.parts)).toHaveLength(50);
  expect(JSON.stringify(cached)).not.toContain("clock_offset_ms");
  expect(JSON.stringify(cached)).not.toContain('"connection"');
  expect(JSON.stringify(cached)).not.toContain('"pending_ids"');
});
