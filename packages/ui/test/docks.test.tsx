import { act, cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { SessionController } from "@jana/client-core";
import { TutorScreen } from "../src/TutorScreen.js";
import { LocaleProvider } from "../src/i18n.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { Fixture, SESSION, id } from "./harness.js";

afterEach(cleanup);

test.each(["question", "hint"] as const)("uia21_dock_card_shared: %s", async (kind) => {
  for (const source of ["dock", "inline"]) {
    const f = new Fixture(); f.startTurn(); const part = id("prt"), request = id("req");
    f.emit({ type: "part.start", part_id: part, kind: "card", index: 0 });
    const card = kind === "hint" ? { card_type: "hint", rung: 2, of: 5, body: "Which force?", actions: ["try_it", "next_hint", "show_step"] }
      : { card_type: "question", prompt: "Which force?", options: [{ id: "gravity", label: "Gravity" }], multi: false, allow_free_text: true };
    f.emit({ type: "card.open", request_id: request, part_id: part, call_id: null, card });
    f.emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 1 }); f.end();
    const posts: { path: string; body: unknown; key: string | null }[] = [];
    let release!: () => void; const pending = new Promise<void>((resolve) => { release = resolve; });
    const session = new SessionController({ endpoint: async () => ({ baseUrl: "http://core.test", token: "synthetic" }) }, f.holder, SESSION, { fetch: async (url, init) => {
      if (init?.method === "POST") { posts.push({ path: new URL(String(url)).pathname, body: JSON.parse(String(init.body)), key: new Headers(init.headers).get("idempotency-key") }); await pending; return Response.json({ status: "accepted" }); }
      return Response.json({ captures: [], document: {}, revision: 0 });
    } });
    const view = render(<LocaleProvider locale="en"><RegistryProvider registry={defaultRegistry()}><StoreProvider holder={f.holder} session={session}><TutorScreen sessionId={SESSION} /></StoreProvider></RegistryProvider></LocaleProvider>);
    const dock = view.container.querySelector<HTMLElement>("[data-request-dock]")!;
    const inline = view.container.querySelector<HTMLElement>(`[data-part-id="${part}"]`)!;
    expect(dock.dataset.requestDock).toBe(request);
    expect(document.activeElement).not.toBe(dock);
    fireEvent.keyDown(window, { code: "KeyD", key: "d", altKey: true });
    expect(dock.contains(document.activeElement)).toBe(true);
    const label = kind === "hint" ? source === "dock" ? "Next hint (3 of 5)" : "Another hint" : "Gravity";
    fireEvent.click(within(source === "dock" ? dock : inline).getByRole("button", { name: label }));
    await waitFor(() => expect(posts).toHaveLength(1));
    for (const node of [dock, inline]) for (const button of within(node).getAllByRole("button")) expect((button as HTMLButtonElement).disabled).toBe(true);
    // An overlapping handler cannot manufacture a second idempotency key or POST.
    expect(await session.answerCard(request, { action: "next_hint" })).toBe("ignored");
    expect(posts[0]?.path).toBe(`/v1/cards/${request}/answer`);
    expect(posts[0]?.body).toEqual({ client_answer_id: posts[0]?.key, answer: kind === "hint" ? { action: "next_hint" } : { option_ids: ["gravity"] } });
    await act(async () => { release(); await pending; });
    f.emit({ type: "card.answered", request_id: request, answer_summary: "accepted", answered_ts: Date.now() });
    expect(view.container.querySelector("[data-request-dock]")).toBeNull();
    expect(inline.querySelector("[data-card-state]")?.getAttribute("data-card-state")).toBe("answered");
    expect(inline.textContent).toContain("Answered"); expect(posts).toHaveLength(1);
    session.close(); cleanup();
  }
});


test("only the oldest open question or hint is docked", () => {
  const f = new Fixture(); f.startTurn();
  const requests = [id("req"), id("req")];
  for (const [index, request] of requests.entries()) {
    const part = id("prt"); f.emit({ type: "part.start", part_id: part, kind: "card", index });
    f.emit({ type: "card.open", request_id: request, part_id: part, call_id: null, card: { card_type: "question", prompt: `Question ${index}`, options: [{ id: "a", label: "A" }], multi: false, allow_free_text: false } });
    f.emit({ type: "part.end", part_id: part, status: "complete", duration_ms: 1 });
  }
  f.end(); const view = f.render(<TutorScreen sessionId={SESSION} />);
  expect([...view.container.querySelectorAll<HTMLElement>("[data-request-dock]")].map((n) => n.dataset.requestDock)).toEqual([requests[0]]);
  f.emit({ type: "card.cancel", request_id: requests[0], reason: "superseded" });
  expect([...view.container.querySelectorAll<HTMLElement>("[data-request-dock]")].map((n) => n.dataset.requestDock)).toEqual([requests[1]]);
});
