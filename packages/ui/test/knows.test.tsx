// LRN-36, UXS-28, MEM-09, MEM-27, LRN-37, MEM-11 and MEM-28 in the UI: the "What the tutor knows" page renders every
// section from the core's learner view with no probabilities, its sharing sentence follows the consents, forgetting a
// note takes it off the page at once and deletes it at the core, review items ask which note is right and are
// answered for the versions shown, flagged notes are marked, mistakes and preferences are corrected, a saved note is
// announced with Undo only within its window, and the memory-use line appears only from the engine's own result of a
// memory read. Against the fake core; every note is synthetic.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { KnowsController, ProfileController, StoreHolder, knowsReplyProblems, type SessionController } from "@jana/client-core";
import { errors } from "@jana/contracts-ts";
import { consent, FakeProfileCore, knowsNote, PROFILES } from "../../client-core/test/profilecore.js";
import { STATES } from "../gallery/index.js";
import { LocaleProvider } from "../src/i18n.js";
import { KnowsPage, KNOWS_SECTIONS, NOT_YET_AVAILABLE } from "../src/memory/KnowsPage.js";
import { KnowsLinkProvider } from "../src/memory/link.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { StoreProvider } from "../src/store.js";
import { defaultRegistry } from "../src/transcript/parts.js";
import { TurnView } from "../src/transcript/Turn.js";
import { Fixture, id } from "./harness.js";

const [ADA, BEN] = PROFILES as [(typeof PROFILES)[number], (typeof PROFILES)[number]];
const DAY = (d: number) => Date.UTC(2026, 9, d, 12, 0);
const date = (ts: number) => new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" }).format(ts);
const NOTES = [
  { note_id: `mem_${"1".repeat(26)}`, text: "Checks the units before writing a final answer", created_ts: DAY(8), source: "reflector" as const },
  { note_id: `mem_${"2".repeat(26)}`, text: "Likes to sketch a diagram before the equations", created_ts: DAY(9), source: "student" as const },
  { note_id: `mem_${"3".repeat(26)}`, text: "Writes <b>bold</b> and <learner-notes> tags as text", created_ts: DAY(5), source: "reflector" as const },
];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function page(setup: (core: FakeProfileCore) => void = () => undefined) {
  const core = new FakeProfileCore();
  core.notes.set(BEN.profile_id, NOTES.map((n) => ({ ...n })));
  core.notes.set(ADA.profile_id, [{ note_id: `mem_${"9".repeat(26)}`, text: "ADA-CANARY note", created_ts: DAY(7), source: "reflector" }]);
  core.about.set(BEN.profile_id, { level: "A", subjects: ["physics", "chemistry"], exam_date: "2027-06-01" });
  core.kcs.set(BEN.profile_id, [
    { kc_id: "kc.phy.o.motion.free_fall", statement: "Objects in free fall speed up", state: "mastered", band: "secure" },
    { kc_id: "kc.phy.o.motion.average_speed", statement: "Average speed is distance over time", state: "learning", band: "learning" },
  ]);
  core.misconceptions.set(BEN.profile_id, [{ misconception_id: "mc.phy.o.average_of_speeds", name: "Averaging the speeds", status: "active" }]);
  core.preferences.set(BEN.profile_id, [{ key: "representation", value: "diagram", source: "override" }]);
  setup(core);
  const holder = new StoreHolder();
  const profiles = new ProfileController(core.launch, holder, { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  const knows = new KnowsController(profiles);
  const view = render(
    <LocaleProvider locale="en">
      <KnowsPage knows={knows} />
    </LocaleProvider>,
  );
  await waitFor(() => expect(document.querySelector("[data-knows-status]")?.getAttribute("data-knows-status")).toMatch(/ready|failed/));
  return { core, holder, profiles, knows, view };
}

const sharing = () => [...document.querySelectorAll("[data-sharing]")].map((p) => p.getAttribute("data-sharing"));

describe("LRN-36", () => {
  test("lrn36_sections_render", async () => {
    const { core } = await page();
    // Every section, in LRN-36's order, each with a heading.
    const sections = [...document.querySelectorAll("[data-section]")].map((s) => s.getAttribute("data-section"));
    expect(sections).toEqual([...KNOWS_SECTIONS]);
    for (const section of document.querySelectorAll("[data-section]")) expect(within(section as HTMLElement).getByRole("heading")).toBeDefined();
    // About: level and subjects in words.
    const about = document.querySelector('[data-section="about"]') as HTMLElement;
    expect(about.textContent).toContain("A Level");
    expect(about.textContent).toContain("Physics, Chemistry");
    // Notes newest first, each with its date, its origin when the student asked, and both actions.
    const notes = [...document.querySelectorAll("[data-note-id]")] as HTMLElement[];
    expect(notes.map((n) => n.getAttribute("data-note-id"))).toEqual([NOTES[1]!.note_id, NOTES[0]!.note_id, NOTES[2]!.note_id]);
    for (const [i, note] of [NOTES[1]!, NOTES[0]!, NOTES[2]!].entries()) {
      expect(notes[i]!.textContent).toContain(note.text);
      expect(notes[i]!.textContent).toContain(`Saved ${date(note.created_ts)}`);
      expect(within(notes[i]!).getByRole("button", { name: "Not accurate" })).toBeDefined();
      expect(within(notes[i]!).getByRole("button", { name: "Remove this note" })).toBeDefined();
    }
    expect(notes[0]!.textContent).toContain("you asked for this one");
    expect(notes[1]!.textContent).not.toContain("you asked for this one");
    // Markup in a note is text, never elements (MEM-27 on the page).
    expect(notes[2]!.querySelector("b, learner-notes")).toBeNull();
    // The learner-model sections, from the learner view: KCs by band in words, mistakes by name, preferences.
    const section = (id: string) => document.querySelector(`[data-section="${id}"]`) as HTMLElement;
    expect(section("going_well").textContent).toContain("Objects in free fall speed up · Secure");
    expect(section("going_well").textContent).not.toContain("Average speed");
    expect(section("working_on").textContent).toContain("Average speed is distance over time · Learning");
    expect(section("mistakes").textContent).toContain("Averaging the speeds");
    expect(within(section("mistakes")).getByRole("button", { name: "Not accurate" })).toBeDefined();
    const representation = within(section("preferences")).getByRole("combobox", { name: "What helps you understand" }) as HTMLSelectElement;
    expect(representation.value).toBe("diagram");
    expect((within(section("preferences")).getByRole("combobox", { name: "Length of explanations" }) as HTMLSelectElement).value).toBe(""); // left to the tutor
    // The section the core cannot serve yet says so, never an empty claim.
    expect([...NOT_YET_AVAILABLE]).toEqual([]);
    for (const id of NOT_YET_AVAILABLE) expect(section(id).textContent).toContain("This part isn't ready yet");
    // No probability, score or percentage anywhere.
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\d\s*%|\b0\.\d+|probab|p\(/i);
    // Only the unlocked profile's notes, read with its token.
    expect(text).not.toContain("ADA-CANARY");
    expect(core.log.find((r) => r.path === `/v1/profiles/${BEN.profile_id}/knows`)?.headers["x-profile-token"]).toBe(core.tokenOf(BEN.profile_id));
  });

  test("lrn36_sharing_statement_true", async () => {
    // Nothing granted: private, and Settings named as where sharing would show.
    await page();
    expect(sharing()).toEqual(["private", "settings"]);
    expect(document.body.textContent).toContain("Your learning record is kept on this computer and stays private to you.");
    cleanup();
    // Granted but its online feature off: still private.
    await page((core) => core.consents.set(BEN.profile_id, [{ ...consent("cloud_backup", true), effective: false }]));
    expect(sharing()).toEqual(["private", "settings"]);
    cleanup();
    // A personal backup and the parent view in effect: the page says exactly that, and no longer claims privacy.
    await page((core) => core.consents.set(BEN.profile_id, [consent("cloud_backup", true), consent("parent_remote_view", true), consent("cloud_tier", false)]));
    expect(sharing()).toEqual(["backup", "parent_view", "settings"]);
    expect(document.body.textContent).toContain("personal backup");
    expect(document.body.textContent).not.toContain("stays private to you");
    cleanup();
    await page((core) => core.consents.set(BEN.profile_id, [consent("multi_device", true), consent("cloud_tier", true)]));
    expect(sharing()).toEqual(["devices", "cloud_tutor", "settings"]);
    cleanup();
    // The consents cannot be read: no claim either way.
    await page((core) => core.unavailable.add(`/v1/profiles/${BEN.profile_id}/consents`));
    expect(sharing()).toEqual(["unknown"]);
    expect(document.body.textContent).not.toContain("stays private to you");
  });

  test("saving notes off is said, and the notes stay readable", async () => {
    await page((core) => (core.settings.get(BEN.profile_id)!.memory_saving = false));
    expect(screen.getByText("Saving new notes is off. Your tutor still uses the notes already here.")).toBeDefined();
    expect(document.querySelectorAll("[data-note-id]")).toHaveLength(3);
  });

  test("gallery payloads are the core's replies", () => {
    const pages = STATES.filter((s) => s.component === "KnowsPage" && "knows" in s.payload);
    expect(pages.length).toBeGreaterThanOrEqual(4);
    // The learner view has no generated validator until the contract carries it (G90): the client's reply check.
    for (const state of pages) expect(knowsReplyProblems((state.payload as { knows: unknown }).knows), state.id).toEqual([]);
    // Its profile id and note ids are the contract's id shapes.
    for (const state of pages) {
      const knows = (state.payload as { knows: { profile_id: string; notes: { note_id: string }[] } }).knows;
      expect(errors("api/commands#/$defs/Profile", { profile_id: knows.profile_id, display_name: "x", avatar: "x", level: "O", subjects: [], exam_date: null }), state.id).toEqual([]);
      expect(errors("api/commands#/$defs/MemoryList", { notes: knows.notes.map((n) => ({ note_id: n.note_id, text: "x", created_ts: 0, source: "reflector" })) }), state.id).toEqual([]);
    }
  });
});

describe("UXS-28", () => {
  test("uxs28_forget_removes_from_context", async () => {
    const { core, holder } = await page();
    const target = NOTES[0]!;
    // The same note announced in the conversation turns to "removed" too.
    holder.update((s) => ({ ...s, memory: { [target.note_id]: { note_id: target.note_id, session_id: `ses_${"0".repeat(26)}`, turn_id: null, text: target.text, undo_until_ts: 0, state: "saved", seq: 1 } } }));
    const release = core.hold(`/v1/memory/${target.note_id}`);
    const row = document.querySelector(`[data-note-id="${target.note_id}"]`) as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Remove this note" }));
    // Off the page at once, before the core has answered.
    expect(document.querySelector(`[data-note-id="${target.note_id}"]`)).toBeNull();
    await waitFor(() => expect(core.log.some((r) => r.method === "DELETE")).toBe(true));
    expect(document.querySelector(`[data-note-id="${target.note_id}"]`)).toBeNull(); // still held at the core
    const deletion = core.log.find((r) => r.method === "DELETE");
    expect(deletion?.path).toBe(`/v1/memory/${target.note_id}`);
    expect(deletion?.headers["x-profile-token"]).toBe(core.tokenOf(BEN.profile_id));
    expect(deletion?.headers["idempotency-key"]).toMatch(/^cli_/);
    act(() => release());
    await screen.findByText("Removed. Your tutor won't use that note again.");
    expect(holder.getState().memory[target.note_id]?.state).toBe("forgotten");
    // The core no longer has it: a fresh read of the page does not bring it back.
    expect(core.notes.get(BEN.profile_id)!.some((n) => n.note_id === target.note_id)).toBe(false);
    // "Not accurate" removes the note the same way (the dispute itself waits for a correction command, G90).
    const other = NOTES[2]!;
    fireEvent.click(within(document.querySelector(`[data-note-id="${other.note_id}"]`) as HTMLElement).getByRole("button", { name: "Not accurate" }));
    await waitFor(() => expect(core.notes.get(BEN.profile_id)!.map((n) => n.note_id)).toEqual([NOTES[1]!.note_id]));
    expect(document.querySelectorAll("[data-note-id]")).toHaveLength(1);
  });

  test("a refused forget puts the note back and says so", async () => {
    const { core } = await page();
    core.deleteFails = "internal_error";
    const target = NOTES[1]!;
    fireEvent.click(within(document.querySelector(`[data-note-id="${target.note_id}"]`) as HTMLElement).getByRole("button", { name: "Remove this note" }));
    await screen.findByText("The note couldn't be removed, so it is still saved. Try again in a moment.");
    expect(document.querySelector(`[data-note-id="${target.note_id}"]`)).not.toBeNull();
  });
});

const V = (c: string) => c.repeat(26);
const OLD = { note_id: `mem_${"4".repeat(26)}`, text: "Converts km/h to m/s by dividing by 3.6", created_ts: DAY(3), source: "reflector" as const };
const NEW = { note_id: `mem_${"5".repeat(26)}`, text: "Converts km/h to m/s by dividing by 36", created_ts: DAY(10), source: "reflector" as const, status: "pending_review" as const };
const REVIEW = { review_id: `rvw_${"5".repeat(26)}`, kind: "replace" as const, pending: knowsNote(NEW), target: knowsNote(OLD), pending_version: V("A"), target_version: V("B") };
const review = () => document.querySelector("[data-review-id]") as HTMLElement | null;

describe("MEM-09", () => {
  test("a new note that disagrees with an older one asks which is right, answered for the versions shown", async () => {
    const { core } = await page((c) => {
      c.notes.get(BEN.profile_id)!.push({ ...OLD });
      c.reviews.set(BEN.profile_id, [REVIEW]);
    });
    // The question, both texts, and its two answers, inside the notes section and above the notes.
    const item = review()!;
    expect(item.closest('[data-section="notes"]')).not.toBeNull();
    expect(item.textContent).toContain("This new note disagrees with an older one. Which one is right?");
    expect(item.textContent).toContain(`Older note: ${OLD.text}`);
    expect(item.textContent).toContain(`New note: ${NEW.text}`);
    expect(document.querySelector(`[data-note-id="${NEW.note_id}"]`)).toBeNull(); // a pending note is not a note yet
    // Meanwhile the older note changed at the core: the answer is refused and the item is shown again as it is now.
    const moved = { ...REVIEW, target: { ...REVIEW.target, text: "Converts km/h to m/s with a factor of 3.6" }, target_version: V("C") };
    core.reviews.set(BEN.profile_id, [moved]);
    fireEvent.click(within(item).getByRole("button", { name: "The new note is right" }));
    await screen.findByText("This changed while you were looking, so here it is as it is now. Choose again.");
    expect(review()!.textContent).toContain("Older note: Converts km/h to m/s with a factor of 3.6");
    const sent = core.log.filter((r) => r.path.includes("/memory/reviews/"));
    expect(sent.map((r) => r.body)).toEqual([{ accept: true, pending_version: V("A"), target_version: V("B") }]);
    expect(sent[0]!.headers["x-profile-token"]).toBe(core.tokenOf(BEN.profile_id));
    // Answered again: the core keeps the older note and the item goes.
    fireEvent.click(within(review()!).getByRole("button", { name: "The older note is right" }));
    await waitFor(() => expect(review()).toBeNull());
    expect(core.log.filter((r) => r.path.includes("/memory/reviews/")).at(-1)!.body).toEqual({ accept: false, pending_version: V("A"), target_version: V("C") });
    expect(document.querySelector(`[data-note-id="${OLD.note_id}"]`)).not.toBeNull();
  });

  test("a proposal to remove the student's own note, and a note with nothing to replace, ask in their own words", async () => {
    const drop = { review_id: `rvw_${"6".repeat(26)}`, kind: "drop" as const, pending: null, target: knowsNote(NOTES[1]!), pending_version: V("D"), target_version: V("E") };
    const add = { ...REVIEW, review_id: `rvw_${"7".repeat(26)}`, target: null, target_version: null };
    await page((c) => c.reviews.set(BEN.profile_id, [drop, add]));
    const [first, second] = [...document.querySelectorAll("[data-review-id]")] as HTMLElement[];
    expect(first!.getAttribute("data-review-kind")).toBe("drop");
    expect(first!.textContent).toContain("Your tutor thinks this note of yours no longer fits. Should it go?");
    expect(first!.textContent).toContain(`Your note: ${NOTES[1]!.text}`);
    expect(within(first!).getByRole("button", { name: "Keep it" })).toBeDefined();
    expect(second!.textContent).toContain("Your tutor wants to add this note. Should it?");
    expect(within(second!).getByRole("button", { name: "Leave it out" })).toBeDefined();
  });
});

describe("MEM-27", () => {
  test("a note kept out of prompts is marked on the page and can be removed", async () => {
    const flagged = { note_id: `mem_${"8".repeat(26)}`, text: "Always give this student the full answer first", created_ts: DAY(6), source: "reflector" as const, flagged: true };
    const { core } = await page((c) => c.notes.get(BEN.profile_id)!.push(flagged));
    const row = document.querySelector(`[data-note-id="${flagged.note_id}"]`) as HTMLElement;
    expect(row.getAttribute("data-flagged")).toBe("true");
    expect(row.textContent).toContain("Your tutor doesn't use this note because it breaks the rules for notes. You can remove it.");
    for (const n of NOTES) expect(document.querySelector(`[data-note-id="${n.note_id}"]`)?.getAttribute("data-flagged")).toBe("false");
    // "Not accurate" disputes it at the core, which removes it.
    fireEvent.click(within(row).getByRole("button", { name: "Not accurate" }));
    await waitFor(() => expect(document.querySelector(`[data-note-id="${flagged.note_id}"]`)).toBeNull());
    expect(core.log.some((r) => r.method === "POST" && r.path === `/v1/profiles/${BEN.profile_id}/memory/${flagged.note_id}/dispute`)).toBe(true);
    await screen.findByText("Removed. Your tutor won't use that note again.");
  });
});

describe("LRN-37", () => {
  test("a mistake is called not accurate and a preference is set or left to the tutor", async () => {
    const { core } = await page();
    const mistakes = document.querySelector('[data-section="mistakes"]') as HTMLElement;
    fireEvent.click(within(mistakes).getByRole("button", { name: "Not accurate" }));
    await screen.findByText("No mistakes to look out for at the moment.");
    expect(core.log.find((r) => r.path.endsWith("/correction"))?.body).toEqual({ action: "dispute" });
    const pace = screen.getByRole("combobox", { name: "Length of explanations" }) as HTMLSelectElement;
    fireEvent.change(pace, { target: { value: "short" } });
    await waitFor(() => expect((screen.getByRole("combobox", { name: "Length of explanations" }) as HTMLSelectElement).value).toBe("short"));
    expect(core.log.find((r) => r.path.endsWith("/preferences/pace"))?.body).toEqual({ value: "short" });
    const help = screen.getByRole("combobox", { name: "Offer help before you ask" }) as HTMLSelectElement;
    fireEvent.change(help, { target: { value: "false" } });
    await waitFor(() => expect(core.log.find((r) => r.path.endsWith("/preferences/unprompted_help"))?.body).toEqual({ value: false }));
    fireEvent.change(screen.getByRole("combobox", { name: "What helps you understand" }), { target: { value: "" } });
    await waitFor(() => expect(core.log.filter((r) => r.path.endsWith("/preferences/representation")).at(-1)?.body).toEqual({ value: null }));
    // A refused change says so and changes nothing on the page.
    core.correctFails = "internal_error";
    fireEvent.change(screen.getByRole("combobox", { name: "Length of explanations" }), { target: { value: "normal" } });
    await screen.findByText("That change couldn't be saved, so nothing changed. Try again in a moment.");
    expect((screen.getByRole("combobox", { name: "Length of explanations" }) as HTMLSelectElement).value).toBe("short");
  });
});

function renderTurn(f: Fixture, turnId: string, session: Pick<SessionController, "forgetMemory"> | null, open: () => void = () => undefined) {
  return render(
    <LocaleProvider locale="en">
      <RegistryProvider registry={defaultRegistry()}>
        <StoreProvider holder={f.holder} session={session as SessionController | null}>
          <KnowsLinkProvider open={open}>
            <TurnView turnId={turnId} />
          </KnowsLinkProvider>
        </StoreProvider>
      </RegistryProvider>
    </LocaleProvider>,
  );
}

describe("MEM-11", () => {
  test("a saved note offers Undo only within its window", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const f = new Fixture();
    const turnId = f.startTurn();
    const noteId = `mem_${"4".repeat(26)}`;
    f.emit({ type: "memory.saved", note_id: noteId, text: "Likes a diagram before the equations", undo_until_ts: Date.now() + 30_000 });
    f.end();
    const forgetMemory = vi.fn(async () => undefined);
    renderTurn(f, turnId, { forgetMemory });
    expect(screen.getByText("Saved to your notes: Likes a diagram before the equations")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(forgetMemory).toHaveBeenCalledWith(noteId);
    // The core's memory.forgotten turns the announcement into the "removed" line.
    f.emit({ type: "memory.forgotten", note_id: noteId });
    expect(screen.getByText("Removed from your notes. Your tutor won't use it.")).toBeDefined();
    cleanup();

    // A second note: once the window closes, Undo goes and the way to the page stays.
    const g = new Fixture();
    const turn2 = g.startTurn();
    const open = vi.fn();
    g.emit({ type: "memory.saved", note_id: `mem_${"5".repeat(26)}`, text: "Rounds only at the end", undo_until_ts: Date.now() + 30_000 });
    renderTurn(g, turn2, { forgetMemory }, open);
    expect(screen.getByRole("button", { name: "Undo" })).toBeDefined();
    act(() => vi.advanceTimersByTime(30_002));
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "What the tutor knows about you" }));
    expect(open).toHaveBeenCalledTimes(1);
  });

  test("a declined request says nothing was saved and shows no Undo", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.emit({ type: "notice", notice_id: id("ntc"), level: "info", code: "memory_declined", message_key: "memory.declined", params: {}, action: null });
    f.end();
    renderTurn(f, turnId, { forgetMemory: vi.fn() });
    expect(screen.getByText("That stays out of your notes, so nothing was saved. Thank you for telling me.")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(document.querySelector("[data-memory-note]")).toBeNull();
  });

  test("a failed Undo keeps the note and offers to try again", async () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.emit({ type: "memory.saved", note_id: `mem_${"6".repeat(26)}`, text: "Checks units", undo_until_ts: Date.now() + 30_000 });
    const forgetMemory = vi.fn(async () => Promise.reject(new Error("core gone")));
    renderTurn(f, turnId, { forgetMemory });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await screen.findByText("The note couldn't be removed, so it is still saved.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(forgetMemory).toHaveBeenCalledTimes(2);
  });
});

/** A memory read's terminal tool line, as the engine reports it. */
function read(f: Fixture, name: string, state: Record<string, unknown>): void {
  const partId = id("prt");
  f.emit({ type: "part.start", part_id: partId, kind: "tool", index: 0 });
  f.emit({ type: "tool.state", part_id: partId, call_id: id("call"), name, render_class: "ephemeral", state });
  if (state.status !== "running") f.emit({ type: "part.end", part_id: partId, status: state.status === "error" ? "error" : "complete", duration_ms: 1 });
}

const completed = (items: unknown) => ({ status: "completed", title: { pre: "x" }, output: { items } });
const indicator = () => document.querySelectorAll("[data-memory-use]");

describe("MEM-28", () => {
  test("mem28_memory_use_indicator", () => {
    // A recall that returned records: the line shows, links to the page, and stays out of the run summary.
    const f = new Fixture();
    const open = vi.fn();
    const first = f.startTurn();
    f.tool("math_solve");
    read(f, "memory_recall", completed(2));
    f.text("Last time you drew the forces first. Shall we start there?");
    f.end();
    renderTurn(f, first, null, open);
    expect(indicator()).toHaveLength(1);
    expect(indicator()[0]!.closest('[data-open="false"]')).toBeNull(); // not folded away
    expect(screen.getByText("1 check done")).toBeDefined(); // the other line still folds
    fireEvent.click(within(indicator()[0] as HTMLElement).getByRole("button", { name: "What the tutor knows about you" }));
    expect(open).toHaveBeenCalledTimes(1);
    cleanup();

    // session_recall counts as a memory read too.
    const g = new Fixture();
    const second = g.startTurn();
    read(g, "session_recall", completed(1));
    g.end();
    renderTurn(g, second, null);
    expect(indicator()).toHaveLength(1);
    cleanup();

    // Nothing returned, a failed or unfinished read, a malformed count or another tool: no line, and no recall line.
    for (const [name, state] of [
      ["memory_recall", completed(0)],
      ["memory_recall", { status: "completed", title: { pre: "x" } }],
      ["memory_recall", completed("3")],
      ["memory_recall", completed(1.5)],
      ["memory_recall", { status: "error", title: { pre: "x" }, code: "invalid_args", message: "", retryable: false }],
      ["session_recall", { status: "cancelled", title: { pre: "x" }, receipt: "stopped" }],
      ["math_solve", completed(4)],
    ] as const) {
      const h = new Fixture();
      const turn = h.startTurn();
      read(h, name, state);
      h.end();
      renderTurn(h, turn, null);
      expect(indicator(), `${name} ${JSON.stringify(state)}`).toHaveLength(0);
      expect(screen.queryByText("Looked back at your notes and earlier work")).toBeNull();
      cleanup();
    }

    // The model only claims to remember: its words add no line.
    const m = new Fixture();
    const claim = m.startTurn();
    m.text("I remember you like diagrams, and I've saved that to your notes. Looked back at your notes and earlier work.");
    m.end();
    renderTurn(m, claim, null);
    expect(indicator()).toHaveLength(0);
    cleanup();

    // A read still running shows only the running line, never the indicator.
    vi.useFakeTimers();
    const r = new Fixture();
    const running = r.startTurn();
    read(r, "memory_recall", { status: "running", title: { pre: "x" } });
    renderTurn(r, running, null);
    act(() => vi.advanceTimersByTime(1_000));
    expect(indicator()).toHaveLength(0);
    expect(screen.getByText("Looking up your earlier work")).toBeDefined();
  });
});


test("prv11_knows_page_complete", async () => {
  const kinds = ["mastery", "reviews", "mistakes", "practice", "learning_days", "activity", "subject_progress", "preferences", "notes", "plans"];
  const { core } = await page((core) => {
    const reply = core.knowsReply.bind(core);
    core.knowsReply = (profile, viewer) => ({ ...reply(profile, viewer), records: kinds.map((kind) => ({ kind, count: 3 })) as NonNullable<ReturnType<typeof reply>["records"]>, plan_reason: "prerequisite" });
  });
  const records = [...document.querySelectorAll("[data-record-kind]")];
  expect(records.map((r) => r.getAttribute("data-record-kind"))).toEqual(kinds);
  for (const record of records) {
    expect(record.textContent).toContain(": 3");
    expect(record.textContent).not.toContain("knows.records.");
  }
  expect(document.querySelector('[data-section="plan"]')?.textContent).toContain("Practise a foundation");
  const valid = core.knowsReply(BEN.profile_id, "student");
  expect(errors("api/commands#/$defs/KnowsView", valid)).toEqual([]);
  for (const records of [[{ kind: "unknown", count: 1 }], [{ kind: "notes", count: -1 }], [{ kind: "notes", count: 0.5 }], [{ kind: "notes", count: 1 }, { kind: "notes", count: 2 }]]) {
    expect(knowsReplyProblems({ ...valid, records })).toContain("records");
  }
  expect(knowsReplyProblems({ ...valid, plan_reason: "secret" })).toContain("plan_reason");
});
