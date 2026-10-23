// UXS-25, UXS-26, AGT-24 and LOC-24 in the app as it is wired, over the fake core (synthetic papers and items): the Mock
// exam place (the sidebar's place and Ctrl+4), a sitting from ready to its report with the clock, the navigator, flag
// and clear, the exam lock on every place that would reach the tutor (Home's Ask box, New question, the tutor, lessons,
// practice and notes), the clock surviving the app being killed (the welcome back before any other screen), submit with
// its confirmation, "Show me why" into the tutor with the item loaded and "Practise these topics"; extra time from
// Settings; and every `sitting.state` of TABLE UXS-25a as a gallery state with its words.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { SubjectMap } from "@jana/client-core";
import { errors } from "@jana/contracts-ts";
import { BASE } from "@jana/i18n";
import { GalleryView, STATES } from "@jana/ui/gallery";
import { FakeProfileCore, type FakeMockPaper } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

const option = (n: number) => ({
  item_id: `itm.phy.o.motion.08${n}0`, pack_id: "pack.phy.o", pack_version: "1.0.1", kc_ids: [`kc.phy.o.motion.synthetic_${n}`], kind: "mcq", stem: `Synthetic question ${n}.`,
  parts: [{ part_id: "a", prompt: `Synthetic question ${n}.`, marks: 1, uses_parts: [], input: { kind: "mcq", options: [{ id: "x", label: `Right ${n}` }, { id: "y", label: `Other ${n}` }] } }],
  visual: null, marks: 1,
});
const PAPER: FakeMockPaper = {
  paper_id: "mck.phy.o.0001", subject: "physics", level: "O", title: "Physics synthetic mock", paper_kind: "paper_1_objective",
  duration_minutes: 60, total_marks: 3, questions: 3, calculator: true,
};

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({
  matches: !query.includes("prefers-color-scheme"), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
  addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
})));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** A fake core whose clock can jump ahead (active time passing while a sitting runs). */
function fakeCore() {
  let now = Date.now(); // Only explicit advances move this clock; wall-clock jitter cannot alter an interruption.
  const core = new FakeProfileCore(() => now);
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "1.0.1", signature_ok: true, size_bytes: 1 });
  core.mockPapers = [PAPER];
  core.mockQuestions = [option(1), option(2), option(3)];
  core.mockRight = (_q, answer) => (answer as { parts: { option_id: string }[] }).parts[0]?.option_id === "x";
  return { core, advance: (ms: number) => { now += ms; } };
}

async function launch(core: FakeProfileCore) {
  render(<App runtime={createRuntime(core.launch, core.fetch)} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  return screen.findByRole("navigation", { name: "Main" });
}

const clock = () => screen.getByRole("timer", { name: "Time left" }).textContent ?? "";
const key = (init: KeyboardEventInit) => fireEvent.keyDown(window, init);

async function startPaper(nav: HTMLElement) {
  fireEvent.click(within(nav).getByRole("button", { name: "Mock exam" }));
  await screen.findByRole("heading", { level: 1, name: "Mock exam" });
  fireEvent.click(await screen.findByRole("button", { name: "Choose this paper" }));
  await screen.findByText(BASE["mock.ready_notice"]!);
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  await screen.findByRole("timer", { name: "Time left" });
}

describe("UXS-25", () => {
  test("uxs25_exam_lock_and_timer", async () => {
    const { core, advance } = fakeCore();
    const nav = await launch(core);
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    await startPaper(nav);
    expect(clock()).toMatch(/^(1:00:00|59:5\d) left$/);
    expect(screen.getByText("2 pauses left")).toBeTruthy();
    // Answer the first question, move on with Alt+→ and flag the second with Alt+F (TABLE LOC-12a); a blank question
    // can be flagged (ASM-16). Both changes are saved (API-27).
    fireEvent.click(screen.getByLabelText("Right 1"));
    key({ key: "ArrowRight", altKey: true });
    await screen.findByText("Question 2 of 3");
    key({ key: "f", code: "KeyF", altKey: true });
    await waitFor(() => expect(core.mockSittings[0]?.answers).toMatchObject({ 1: { flagged: false }, 2: { answer: null, flagged: true } }));
    const navigator = screen.getByRole("navigation", { name: "Questions" });
    expect(within(navigator).getByRole("button", { name: "Question 1: Answered" })).toBeTruthy();
    expect(within(navigator).getByRole("button", { name: "Question 2: Not answered, Flagged for review" })).toBeTruthy();
    expect(within(navigator).getByRole("button", { name: "Question 3: Not seen yet" })).toBeTruthy();
    // The tutor is unreachable by any route until submit (AGT-24): Home has no Ask box and says why, with the time
    // left; New question is gone; practice, notes and a recent session say so too. Nothing asks the core for a session.
    const sessionsBefore = core.log.filter((r) => r.method === "POST" && r.path === "/v1/sessions").length;
    key({ key: "1", code: "Digit1", ctrlKey: true });
    const home = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-exam-lock='tutor']");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(home.textContent).toContain(BASE["mock.lock.body"]);
    expect(home.textContent).toMatch(/\d+:\d\d left on your mock\./);
    expect(document.querySelector("[data-composer], [contenteditable='true']")).toBeNull();
    expect(within(nav).queryByRole("button", { name: "New question" })).toBeNull();
    key({ key: "3", code: "Digit3", ctrlKey: true });
    await waitFor(() => expect(document.querySelector("[data-exam-lock='practice']")).not.toBeNull());
    fireEvent.click(within(nav).getByRole("button", { name: "Notes and saved" }));
    await waitFor(() => expect(document.querySelector("[data-exam-lock='notes']")).not.toBeNull());
    fireEvent.click(within(within(nav).getByRole("region", { name: "Recent sessions" })).getAllByRole("button")[0]!);
    await waitFor(() => expect(document.querySelector("[data-exam-lock='tutor']")).not.toBeNull());
    expect(core.log.filter((r) => r.method === "POST" && r.path === "/v1/sessions")).toHaveLength(sessionsBefore);
    expect(core.log.some((r) => r.path.endsWith("/turns") || r.path === "/v1/practice/sets")).toBe(false);
    // "Back to the mock" returns to the paper where it was.
    fireEvent.click(screen.getByRole("button", { name: "Back to the mock" }));
    await screen.findByText("Question 2 of 3");

    // Ten minutes of the paper pass, then the app is killed. On the next launch the welcome back comes before any other
    // screen, with the time left as it was; the clock did not run while the app was closed (ASM-16).
    advance(10 * 60_000);
    core.interruptMocks();
    const kept = core.mockSittings[0]!.duration_ms - core.mockSittings[0]!.elapsed_ms;
    cleanup();
    advance(3 * 60 * 60_000);
    const again = await launch(core);
    await screen.findByText(`Welcome back. ${Math.ceil(kept / 60_000)} minutes left.`);
    expect(screen.queryByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ })).toBeNull();
    expect(within(again).getByRole("button", { name: "Mock exam" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("button", { name: "Continue the mock" }));
    await screen.findByRole("timer", { name: "Time left" });
    expect(clock()).toMatch(/^(50:00|49:5\d) left$/);
    expect(within(screen.getByRole("navigation", { name: "Questions" })).getByRole("button", { name: "Question 1: Answered" })).toBeTruthy();

    // Submit asks first (Ctrl+Enter opens it); "Keep working" keeps the paper open; "Submit" marks it.
    key({ key: "Enter", ctrlKey: true });
    const confirm = await screen.findByRole("alertdialog", { name: BASE["mock.submit_confirm"]! });
    fireEvent.click(within(confirm).getByRole("button", { name: "Keep working" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Submit paper" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Submit" }));
    await screen.findByRole("heading", { name: "1 out of 3" });
    // The lock is gone: Home has its Ask box again.
    key({ key: "1", code: "Digit1", ctrlKey: true });
    await waitFor(() => expect(document.querySelector("[contenteditable='true']")).not.toBeNull());
    expect(document.querySelector("[data-exam-lock]")).toBeNull();
  });

  test("uxs25_sitting_states", async () => {
    // Every `sitting.state` of the mock-exam contract has a gallery state with its TABLE UXS-25a words.
    const words: Record<string, string> = {
      ready: BASE["mock.ready_notice"]!, in_progress: "2 pauses left", paused: "Paused. 7 minutes of pause time left.", interrupted: "Welcome back. 41 minutes left.",
      submitted: BASE["mock.marking"]!, marked: BASE["mock.report.show_me_why"]!, reviewed: BASE["mock.report.show_me_why"]!,
      abandoned: "This mock wasn't finished within 7 days, so it was closed. Your answers are kept.",
    };
    for (const [sitting, text] of Object.entries(words)) {
      const state = STATES.find((s) => s.component === "MockSitting" && s.state !== "error-retriable" && (s.payload as { view: { exam: { state: string } } }).view.exam.state === sitting);
      expect(state, sitting).toBeDefined();
      const { container } = render(<GalleryView state={state!} />);
      expect(container.textContent, sitting).toContain(text);
      cleanup();
    }
    // The remaining time after an app kill equals the time before it.
    const { core, advance } = fakeCore();
    const nav = await launch(core);
    await startPaper(nav);
    advance(7 * 60_000);
    const sitting = core.mockSittings[0]!;
    expect(core.mockLocked(sitting.profile_id)).toBe(true); // reads the sitting's clock now
    const before = sitting.duration_ms - sitting.elapsed_ms;
    core.interruptMocks();
    advance(48 * 60 * 60_000);
    expect(core.mockLocked(sitting.profile_id)).toBe(true);
    expect(sitting.state).toBe("interrupted");
    expect(sitting.duration_ms - sitting.elapsed_ms).toBe(before);
    expect(sitting.interruptions.at(-1)?.remaining_ms).toBe(before);
    // The app shows that same time when it opens again.
    cleanup();
    await launch(core);
    await screen.findByText(`Welcome back. ${Math.ceil(before / 60_000)} minutes left.`);
  });

  test("test_loc24_extra_time_shown", async () => {
    const { core } = fakeCore();
    for (const settings of core.settings.values()) settings.extra_time_percent = 25;
    const nav = await launch(core);
    fireEvent.click(within(nav).getByRole("button", { name: "Mock exam" }));
    await screen.findByText("With your extra time: 75 minutes");
    fireEvent.click(screen.getByRole("button", { name: "Choose this paper" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await screen.findByRole("timer", { name: "Time left" });
    // With 25% extra time a 60-minute paper allows 75 minutes, and the header says so (LOC-24).
    expect(clock()).toMatch(/^(1:15:00|1:14:5\d) left$/);
    expect(screen.getByText("Extra time: 25%")).toBeTruthy();
  });

  test("extra time is an accessibility preference in Settings (ASM-24)", async () => {
    const { core } = fakeCore();
    await launch(core);
    key({ key: ",", ctrlKey: true });
    const group = await screen.findByRole("radiogroup", { name: "Extra time in mock exams" });
    expect(within(group).getByRole("radio", { name: "None" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(group).getByRole("radio", { name: "+25%" }));
    await waitFor(() => expect(core.log.some((r) => r.method === "PATCH" && (r.body as { extra_time_percent?: number } | undefined)?.extra_time_percent === 25)).toBe(true));
  });
});

describe("UXS-26", () => {
  test("uxs26_show_me_why_links", async () => {
    const { core } = fakeCore();
    const nav = await launch(core);
    await startPaper(nav);
    fireEvent.click(screen.getByLabelText("Right 1"));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(await screen.findByLabelText("Other 2"));
    await waitFor(() => expect(Object.keys(core.mockSittings[0]?.answers ?? {}).sort()).toEqual(["1", "2"]));
    fireEvent.click(screen.getByRole("button", { name: "Submit paper" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Submit" }));
    await screen.findByRole("heading", { name: "1 out of 3" });
    // Every answer short of full marks links into the tutor; a full-marks answer does not.
    const rows = [...document.querySelectorAll<HTMLElement>("[data-review-question]")];
    expect(rows.map((r) => [r.dataset.reviewQuestion, r.dataset.reviewVerdict])).toEqual([["1", "full"], ["2", "none"], ["3", "unanswered"]]);
    for (const row of rows) expect(within(row).queryByRole("button", { name: "Show me why" }) !== null, row.dataset.reviewQuestion).toBe(row.dataset.reviewVerdict !== "full");
    // "Show me why" opens a review session with the item loaded (origin exam_review), and its header leads back.
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Show me why" }));
    const back = await screen.findByRole("button", { name: "Back to the mock report" });
    expect(core.reviewed).toEqual([`${core.mockSittings[0]!.exam_id.slice(4)}:2`]);
    const review = core.log.find((r) => r.method === "POST" && r.path === "/v1/sessions" && (r.body as { origin: { kind: string } }).origin.kind === "exam_review");
    expect(review?.body).toMatchObject({ mode: "guided", subject: "physics", origin: { kind: "exam_review" } });
    fireEvent.click(back);
    await screen.findByRole("heading", { name: "1 out of 3" });
    // "Practise these topics" opens the follow-up set the report made (ASM-20).
    fireEvent.click(screen.getByRole("button", { name: "Practise these topics" }));
    await waitFor(() => expect(core.log.some((r) => r.method === "GET" && /^\/v1\/practice\/sets\/set_/.test(r.path))).toBe(true));
    expect(within(nav).getByRole("button", { name: "Practice" }).getAttribute("aria-current")).toBe("page");
  });
});


test("uxs26_practice_weak_kcs_to_plan", async () => {
  const { core } = fakeCore();
  core.practiceServed = true;
  core.practiceItems = [option(2), option(3)];
  const source = (STATES.find((s) => s.id === "subject-map.canonical.topic-sheet")!.payload as { map: SubjectMap }).map;
  const map = structuredClone(source);
  const first = map.sections[0]!.topics[0]!;
  map.sections = [{ ...map.sections[0]!, topics: [1, 2, 3].map((n) => ({
    ...first, node_id: `cur.phy.o.topic_${n}`, title: `Topic ${n}`,
    kcs: [{ ...first.kcs[0]!, kc_id: option(n).kc_ids[0]!, statement: `Skill ${n}`, state: "not_started" }],
    lessons: first.lessons.map((l) => ({ ...l, kc_ids: [option(n).kc_ids[0]!] })),
  })) }];
  core.maps.set(map.subject_id, map);
  core.propose([{ kind: "main", kc_ids: option(1).kc_ids, minutes: 20 }]);
  const nav = await launch(core);
  await startPaper(nav);
  fireEvent.click(screen.getByLabelText("Right 1"));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(await screen.findByLabelText("Other 2"));
  fireEvent.click(screen.getByRole("button", { name: "Submit paper" }));
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Submit" }));
  await screen.findByRole("heading", { name: "1 out of 3" });
  const practise = document.querySelector("[data-practise-ref]") as HTMLElement;
  await waitFor(() => expect(practise.textContent).toContain("Skill 2"));
  expect(practise.textContent).toContain("Skill 3");
  expect(practise.textContent).not.toContain("Skill 1");
  expect(core.log.some((r) => r.method === "GET" && r.path.startsWith("/v1/practice/sets/"))).toBe(false);
  fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
  expect(core.currentPlan()?.blocks).toMatchObject([{ reason_code: "mock_follow_up", kc_ids: [...option(2).kc_ids, ...option(3).kc_ids] }]);
  // Several topics: the title counts them and their names follow, not one long title of names.
  await waitFor(() => expect(document.querySelector("[data-plan]")?.textContent).toContain("Practise 2 topics from your mock"));
  const main = document.querySelector('[data-plan-block="main"]') as HTMLElement;
  expect(main.textContent).toContain("Topic 2 · Topic 3");
  expect(main.textContent).not.toContain("Topic 1");
  fireEvent.click(within(document.querySelector("[data-plan]") as HTMLElement).getByRole("button", { name: "Start" }));
  await waitFor(() => expect(core.log.find((r) => r.method === "POST" && r.path === "/v1/practice/sets")?.body).toMatchObject({ kc_ids: [...option(2).kc_ids, ...option(3).kc_ids] }));
  expect(core.log.some((r) => r.path.startsWith("/v1/lessons/"))).toBe(false);
});

test("inp34_capture_locked_in_exam: photo entry points stop in every sitting state while typed answers save", async () => {
  const { core } = fakeCore();
  const first = option(1);
  core.mockQuestions[0] = { ...first, kind: "numeric", parts: [{ ...first.parts[0]!, input: { kind: "numeric", unit_prompt: null } }] };
  expect(errors("api/commands#/$defs/PracticeItem", core.mockQuestions[0])).toEqual([]);
  let nav = await launch(core);
  await startPaper(nav);
  const capturesBefore = core.log.filter((r) => /\/captures(?:\/|$)/.test(r.path)).length;
  const assertLocked = () => {
    const root = document.querySelector<HTMLElement>("[data-sitting-state]")!;
    const photo = within(root).getByRole("button", { name: "Photo of a question" });
    expect(photo).toHaveProperty("disabled", true);
    expect(root.textContent).toContain("Photos are off during the mock exam.");
    fireEvent.click(photo);
    expect(within(root).queryByRole("dialog", { name: "Photo of a question" })).toBeNull();
    for (const mime of ["image/jpeg", "application/pdf"]) {
      const file = new File(["synthetic file must not be read"], "synthetic", { type: mime });
      expect(fireEvent.drop(root, { dataTransfer: { files: [file], types: ["Files"] } })).toBe(false);
      expect(fireEvent.paste(root, { clipboardData: { files: [file], types: ["Files"] } })).toBe(false);
    }
    expect(root.querySelector('input[type="file"]')).toBeNull();
    expect(core.log.filter((r) => /\/captures(?:\/|$)/.test(r.path))).toHaveLength(capturesBefore);
  };
  assertLocked();
  fireEvent.change(screen.getByRole("textbox", { name: "Your answer" }), { target: { value: "12" } });
  await waitFor(() => expect(core.mockSittings[0]?.answers["1"]?.answer).toMatchObject({ parts: [{ kind: "numeric", value: "12" }] }));
  fireEvent.click(screen.getByRole("button", { name: /Pause/ }));
  await screen.findByText(/Paused\./);
  assertLocked();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByText("Question 1 of 3");
  core.interruptMocks(); cleanup(); nav = await launch(core);
  await screen.findByText(/Welcome back\./);
  assertLocked();
  fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
  const lock = await waitFor(() => {
    const el = document.querySelector<HTMLElement>("[data-exam-lock='tutor']"); expect(el).not.toBeNull(); return el!;
  });
  expect(within(lock).getByRole("button", { name: "Photo of a question" })).toHaveProperty("disabled", true);
  expect(lock.textContent).toContain("Photos are off during the mock exam.");
});
