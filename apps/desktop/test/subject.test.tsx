// UXS-14 and D94 in the app as it is wired: the engine moves a new asked session to its first question's subject with
// `session.updated`, and the header's subject chip, the session's row in Recent and Home's chosen subject follow it
// without reopening the session; the confirm card naming another subject starts the same question there, in a new
// session started by asking, and "Keep going here" leaves the session as it is. Against the fake core; the engine's
// events are folded into the app's store as the stream would deliver them.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { reduce, type Envelope } from "@jana/client-core";
import { FakeProfileCore, PROFILES } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

const ADA = PROFILES[0]!;
const TURN = `trn_${ADA.session_id.slice(4)}`;
const TOPIC = "cur.phy.o.motion";

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({
  matches: true, media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
  addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
})));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const pack = (subject: string) => ({ pack_id: `pack.${subject}.o`, subject, level: "O" as const, version: "0.1.0", signature_ok: true, size_bytes: 1 });
const posts = (fake: FakeProfileCore, path: string) => fake.log.filter((r) => r.method === "POST" && r.path === path).map((r) => r.body as Record<string, unknown>);
const id = (prefix: string, n: number) => `${prefix}_${String(n).padStart(26, "0")}`;

let seq = 1000;
/** One engine event on Ada's session, as the stream delivers it. */
function deliver(runtime: ReturnType<typeof createRuntime>, event: Record<string, unknown>): void {
  seq += 1;
  const envelope = { v: 1, channel: "session", epoch: "ep_profiles", seq, ts: 5, session_id: ADA.session_id, turn_id: TURN, event } as unknown as Envelope;
  runtime.holder.update((s) => reduce(s, envelope));
}

/** Ada opens on Home with mathematics and physics installed; the tutor starts in mathematics, the first of them. */
async function open() {
  const fake = new FakeProfileCore();
  fake.packs.push(pack("phy"), pack("mth"));
  const runtime = createRuntime(fake.launch, fake.fetch);
  render(<App runtime={runtime} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  const nav = await screen.findByRole("navigation", { name: "Main" });
  await waitFor(() => expect(posts(fake, "/v1/sessions").at(-1)).toMatchObject({ subject: "mathematics", origin: { kind: "ask", ref: null } }));
  await waitFor(() => expect(runtime.holder.getState().sessions[ADA.session_id]?.subject).toBe("mathematics"));
  return { fake, runtime, nav };
}

function chip(name: string): HTMLElement {
  return within(screen.getByRole("group", { name: "Choose a subject" })).getByRole("button", { name });
}

/** The subject the tutor header's chip shows. */
function headerSubject(): string {
  return document.querySelector<HTMLSelectElement>("select")?.selectedOptions[0]?.textContent ?? "";
}

function dot(row: HTMLElement): string | null {
  return row.querySelector("[data-subject-dot]")?.getAttribute("data-subject-dot") ?? null;
}

describe("UXS-14 and D94", () => {
  test("uxs14_subject_follows_the_session", async () => {
    const { fake, runtime, nav } = await open();
    await waitFor(() => expect(chip("Mathematics").getAttribute("aria-pressed")).toBe("true"));
    const recent = within(nav).getByRole("region", { name: "Recent sessions" });
    const row = () => within(recent).getByRole("button", { name: new RegExp(ADA.canary) });
    await waitFor(() => expect(dot(row())).toBe("mathematics"));
    const made = posts(fake, "/v1/sessions").length;
    // The engine moved the session to physics: the core keeps it, and the stream says so.
    fake.sessionsMade.set(ADA.session_id, { subject: "physics", topic_id: TOPIC });
    deliver(runtime, { type: "session.updated", subject: "physics", topic_id: TOPIC });
    // Home's chosen subject follows it.
    await waitFor(() => expect(chip("Physics").getAttribute("aria-pressed")).toBe("true"));
    expect(chip("Mathematics").getAttribute("aria-pressed")).toBe("false");
    // The session's row in Recent is read again and carries the new subject.
    await waitFor(() => expect(dot(row())).toBe("physics"));
    // The header's subject chip in the tutor shows it too.
    fireEvent.click(row());
    await waitFor(() => expect(headerSubject()).toBe("Physics"));
    // No new session was made for the change.
    expect(posts(fake, "/v1/sessions")).toHaveLength(made);
  });

  test("uxs14_new_subject_card_starts_a_question", async () => {
    const { fake, runtime, nav } = await open();
    const recent = within(nav).getByRole("region", { name: "Recent sessions" });
    fireEvent.click(await within(recent).findByRole("button", { name: new RegExp(ADA.canary) }));
    await waitFor(() => expect(headerSubject()).toBe("Mathematics"));
    // The engine offers the question as a new one in physics: a confirm card naming that subject.
    const body = {
      card_type: "confirm", purpose: "other", title: "This question looks like Physics",
      body: "This chat is for Mathematics. Start a new question in Physics with the same words, or keep going here.",
      confirm_label_key: "card.new_subject.start", cancel_label_key: "card.new_subject.stay", subject: "physics",
    };
    const offer = (n: number) => {
      deliver(runtime, { type: "part.start", part_id: id("prt", 800 + n), kind: "card", index: n });
      deliver(runtime, { type: "card.open", request_id: id("req", 800 + n), part_id: id("prt", 800 + n), call_id: null, card: body });
      deliver(runtime, { type: "part.end", part_id: id("prt", 800 + n), status: "complete" });
    };
    offer(1);
    // "Keep going here": the answer is sent and nothing else happens.
    fireEvent.click(await screen.findByRole("button", { name: "Keep going here" }));
    await waitFor(() => expect(posts(fake, `/v1/cards/${id("req", 801)}/answer`)).toHaveLength(1));
    expect(posts(fake, `/v1/cards/${id("req", 801)}/answer`)[0]).toMatchObject({ answer: { action: "cancel" } });
    const made = posts(fake, "/v1/sessions").length;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(posts(fake, "/v1/sessions")).toHaveLength(made);
    expect(posts(fake, `/v1/sessions/${ADA.session_id}/turns`)).toHaveLength(0);
    // "Start a new question": a new session started by asking in physics, which asks the same words.
    offer(2);
    const start = await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: "Start a new question" }).filter((b) => !(b as HTMLButtonElement).disabled);
      expect(buttons).toHaveLength(1);
      return buttons[0]!;
    });
    fireEvent.click(start);
    await waitFor(() => expect(posts(fake, "/v1/sessions").length).toBe(made + 1));
    expect(posts(fake, "/v1/sessions").at(-1)).toMatchObject({ subject: "physics", level: "O", mode: "guided", origin: { kind: "ask", ref: null } });
    // One message (a resend keeps its client id, API-31): the same words, asked.
    const asked = () => new Set(posts(fake, `/v1/sessions/${ADA.session_id}/turns`).map((b) => b.client_message_id));
    await waitFor(() => expect(asked().size).toBe(1));
    expect(posts(fake, `/v1/sessions/${ADA.session_id}/turns`)[0]).toMatchObject({ intent: "ask", content: [{ type: "text", text: `My question: ${ADA.canary}` }] });
    await waitFor(() => expect(headerSubject()).toBe("Physics"));
  });
});
