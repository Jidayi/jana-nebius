// UXS-25, ASM-16, API-27 and AGT-24 from the client's side: the papers and sittings the core lists
// (`GET /v1/mocks`, `MockList`), a sitting from `ready` to its report, the clock counted down from the core's `remaining_ms` and read
// again at zero (time-up submits), answers and flags saved as full replacements (a cleared answer is null, its flag
// kept), the lock while a sitting is open, and a core that does not list mocks. Over the fake core, with a fake clock
// and synthetic items.
import { describe, expect, test } from "vitest";
import { CLIENT_KEYS, MockController, ProfileController, StoreHolder, examLock, pauseBudget, remainingAt } from "../src/index.js";
import { FakeProfileCore, PROFILES, type FakeMockPaper } from "./profilecore.js";

const ITEM = {
  item_id: "itm.phy.o.synthetic.0001", pack_id: "pack.phy.o", pack_version: "1.0.0", kc_ids: ["kc.phy.o.motion.speed"], kind: "mcq",
  stem: "A synthetic question.", parts: [{ part_id: "a", prompt: "Choose one.", uses_parts: [], marks: 1, input: { kind: "mcq", options: [{ id: "x", label: "One" }, { id: "y", label: "Two" }] } }],
  visual: null, marks: 1,
};

export const PAPER: FakeMockPaper = {
  paper_id: "mck.phy.o.0001", subject: "physics", level: "O", title: "Physics mock, synthetic paper", paper_kind: "paper_1_objective",
  duration_minutes: 60, total_marks: 3, questions: 3, calculator: true,
};

async function opened() {
  let now = 1_800_000_000_000;
  const core = new FakeProfileCore(() => now);
  core.mockPapers = [PAPER];
  core.mockQuestions = [ITEM, { ...ITEM, item_id: "itm.phy.o.synthetic.0002" }, { ...ITEM, item_id: "itm.phy.o.synthetic.0003" }];
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: (input, init) => core.fetch(input, init) });
  await profiles.load();
  expect(await profiles.unlock(PROFILES[0]!.profile_id)).toBe(true);
  const mocks = new MockController(profiles, () => now);
  await mocks.load();
  return { core, mocks, profiles, advance: (ms: number) => { now += ms; }, now: () => now };
}

const choice = (option: string) => ({ parts: [{ part_id: "a", kind: "mcq" as const, option_id: option }] });

describe("UXS-25", () => {
  test("manual submission retains unsaved answers after a failed save and retries safely", async () => {
    const { core, mocks } = await opened();
    await mocks.choose(PAPER.paper_id); await mocks.start();
    const original = core.fetch;
    let fail = true;
    core.fetch = async (input, init) => init?.method === "PUT" && String(input).includes("/answers/") && fail
      ? new Response(JSON.stringify({ error: { code: "internal_error", retryable: true } }), { status: 503 }) : original(input, init);
    mocks.setAnswer("1", { answer: choice("y") });
    await mocks.submit();
    expect(mocks.getView()).toMatchObject({ result: null, saveFailed: true, unsaved: ["1"], acting: false, exam: { state: "in_progress" } });
    expect(core.log.some((r) => r.path.endsWith("/submit"))).toBe(false);
    fail = false;
    await mocks.submit();
    expect(mocks.getView().result?.unanswered).not.toContain("1");
    expect(mocks.getView().unsaved).toEqual([]);
  });

  test("submission drains an answer edited while its earlier revision is saving", async () => {
    const { core, mocks } = await opened();
    await mocks.choose(PAPER.paper_id); await mocks.start();
    const original = core.fetch;
    let release!: () => void;
    const waiting = new Promise<void>((resolve) => { release = resolve; });
    let first = true;
    core.fetch = async (input, init) => {
      if (first && init?.method === "PUT" && String(input).includes("/answers/")) { first = false; await waiting; }
      return original(input, init);
    };
    mocks.setAnswer("1", { answer: choice("x") });
    const submitting = mocks.submit();
    mocks.setAnswer("1", { answer: choice("y") });
    release(); await submitting;
    const saved = core.log.filter((r) => r.method === "PUT" && r.path.endsWith("/answers/1"));
    expect(saved.map((r) => r.body)).toEqual([{ answer: choice("x"), flagged: false }, { answer: choice("y"), flagged: false }]);
    expect(mocks.getView().result?.unanswered).not.toContain("1");
  });
  test("the place lists the papers on this computer, and a chosen paper waits ready with its notice", async () => {
    const { mocks } = await opened();
    expect(mocks.getView()).toMatchObject({ status: "ready", papers: [PAPER], sittings: [] });
    await mocks.choose(PAPER.paper_id);
    const view = mocks.getView();
    expect(view.exam?.state).toBe("ready");
    expect(view.current).toBe("1");
    expect(examLock(view)).toBeNull(); // a ready paper locks nothing yet
  });

  test("test_asm16_client_clock_counts_active_time_from_the_core", async () => {
    const { mocks, advance, now } = await opened();
    await mocks.choose(PAPER.paper_id);
    await mocks.start();
    const lock = examLock(mocks.getView())!;
    expect(lock.state).toBe("in_progress");
    advance(90_000);
    expect(remainingAt(lock, now())).toBe(60 * 60_000 - 90_000);
    // A pause stops the clock; its budget counts down instead (ASM-16).
    await mocks.pause();
    const paused = examLock(mocks.getView())!;
    advance(120_000);
    expect(remainingAt(paused, now())).toBe(60 * 60_000 - 90_000);
    expect(pauseBudget(mocks.getView().exam!, mocks.getView().readAt, now())).toEqual({ pauses: CLIENT_KEYS.mock_pause_count - 1, ms: CLIENT_KEYS.mock_pause_minutes * 60_000 - 120_000 });
    await mocks.resume();
    expect(mocks.getView().exam?.remaining_ms).toBe(60 * 60_000 - 90_000);
  });

  test("test_api27_flag_and_clear_saved_as_full_replacements", async () => {
    const { core, mocks } = await opened();
    await mocks.choose(PAPER.paper_id);
    await mocks.start();
    mocks.toggleFlag("2"); // a blank question can be flagged
    mocks.setAnswer("1", { answer: choice("x") });
    expect(mocks.getView().unsaved.sort()).toEqual(["1", "2"]);
    await mocks.flush();
    mocks.clear("1");
    mocks.toggleFlag("1");
    await mocks.flush();
    const puts = core.log.filter((r) => r.method === "PUT").map((r) => [r.path.split("/").pop(), r.body]);
    expect(puts).toEqual([
      ["1", { answer: choice("x"), flagged: false }],
      ["2", { answer: null, flagged: true }],
      ["1", { answer: null, flagged: true }],
    ]);
    expect(mocks.getView()).toMatchObject({ unsaved: [], saveFailed: false });
    await mocks.submit();
    expect(mocks.getView().result?.unanswered).toEqual(["1", "2", "3"]);
    expect(mocks.getView().result?.flagged).toEqual(["1", "2"]);
  });

  test("time up: the clock reaches zero, the core submits, and the report follows", async () => {
    const { mocks, advance } = await opened();
    await mocks.choose(PAPER.paper_id);
    await mocks.start();
    mocks.setAnswer("3", { answer: choice("y") });
    await mocks.flush();
    advance(60 * 60_000);
    await mocks.timeUp();
    const view = mocks.getView();
    expect(view).toMatchObject({ timeUp: true, marking: false, exam: { state: "marked" } });
    expect(view.result?.score).toBe(1);
    expect(examLock(view)).toBeNull();
  });

  test("test_agt24_lock_while_a_sitting_is_open", async () => {
    const { core, mocks, profiles } = await opened();
    await mocks.choose(PAPER.paper_id);
    await mocks.start();
    core.interruptMocks(); // the app was killed
    const reopened = new MockController(profiles);
    await reopened.load();
    const lock = examLock(reopened.getView());
    expect(lock).toMatchObject({ state: "interrupted", remainingMs: 60 * 60_000 });
    await reopened.open(lock!.examId);
    await reopened.resume();
    expect(examLock(reopened.getView())?.state).toBe("in_progress");
    await reopened.submit();
    expect(examLock(reopened.getView())).toBeNull();
    // A marked sitting reopens on its report.
    const later = new MockController(profiles);
    await later.load();
    expect(later.getView().sittings[0]).toMatchObject({ state: "marked", score: 0, max_score: 3 });
    await later.open(later.getView().sittings[0]!.exam_id);
    expect(later.getView().result?.max_score).toBe(3);
  });

  test("a core that does not list mocks says so, and a malformed list is refused", async () => {
    const { core, mocks } = await opened();
    core.mocksServed = false;
    await mocks.load();
    expect(mocks.getView().status).toBe("unavailable");
    core.mocksServed = true;
    core.mockPapers = [{ ...PAPER, paper_id: "not-a-paper" }];
    await mocks.load();
    expect(mocks.getView().status).toBe("failed");
  });
});
