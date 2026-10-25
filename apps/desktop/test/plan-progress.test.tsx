// UXS-12, UXS-27, UXS-51, LRN-34 and PRM-03 in the app as it is wired, over the fake core (synthetic ideas and items):
// Home renders its plan while the tutor model still loads and keeps a question typed meanwhile until the tutor is
// ready; the plan card's Start, Change and Not today answer the card, a finished plan offers Keep learning and a
// started one resumes; a checked practice answer moves the idea's bar within the LRN-34 budget; Progress (the sidebar's
// place and Ctrl+5) shows the learner model in words, the grade band only in the board's own letters (D27); where no
// tutor answers, Home searches the worked solutions; Settings → Tutor renames the tutor and picks its character.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { CLIENT_KEYS, type ProgressView } from "@jana/client-core";
import type { ModelCatalogue } from "@jana/contracts-ts";
import { STATES } from "@jana/ui/gallery";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";
import { menuItem } from "./student-menu.js";

type Item = Record<string, unknown> & { item_id: string; kc_ids: string[] };
const LESSON = STATES.find((s) => s.id === "lesson-player.canonical")!.payload as { lesson: { blocks: { items?: Item[] }[] } };
const ITEMS = LESSON.lesson.blocks.flatMap((b) => b.items ?? []).slice(0, 3);

beforeEach(() => vi.stubGlobal("matchMedia", (query: string) => ({
  matches: !query.includes("prefers-color-scheme"), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
  addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
})));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const kcs = (topic: string, states: ProgressView["subjects"][number]["topics"][number]["kcs"][number]["state"][]) => states.map((state, i) => ({
  kc_id: `kc.phy.o.${topic}.idea_${i + 1}`, state, band: state === "not_started" ? "not_started" as const : state === "mastered" || state === "needs_review" ? "secure" as const : "learning" as const,
}));

/** A synthetic progress view: two physics topics, a streak and an idea that moved today. */
function progressView(grade: Record<string, unknown> = { status: "no_scale", checked: 12, needed: 30 }): ProgressView {
  const motion = kcs("motion", ["mastered", "needs_review", "learning", "ready_to_check"]);
  const forces = kcs("forces", ["not_started", "moved_on", "learning"]);
  const count = (list: typeof motion) => ({ not_started: list.filter((k) => k.band === "not_started").length, learning: list.filter((k) => k.band === "learning").length, secure: list.filter((k) => k.band === "secure").length });
  return {
    subjects: [{
      subject: "physics", bands: count([...motion, ...forces]),
      topics: [{ topic_id: "cur.phy.o.motion", title: "Motion", bands: count(motion), kcs: motion }, { topic_id: "cur.phy.o.forces", title: "Forces", bands: count(forces), kcs: forces }],
      history: [{ week_start: "2026-09-28", learning: 1, secure: 0 }, { week_start: "2026-10-05", learning: 3, secure: 1 }, { week_start: "2026-10-12", learning: 4, secure: 2 }],
      grade: grade as unknown as ProgressView["subjects"][number]["grade"],
    }],
    time_studied: { minutes_7d: 95, sessions_7d: 4, minutes_total: 240 }, streak: { days: 5, freezes_left: 1, counted_today: true }, moved_today: ["kc.phy.o.motion.idea_3"],
  };
}

function fakeCore(setup: (core: FakeProfileCore) => void = () => undefined) {
  const core = new FakeProfileCore();
  core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "0.1.0", signature_ok: true, size_bytes: 1 });
  core.progress = progressView();
  setup(core);
  return core;
}

async function launch(core: FakeProfileCore) {
  render(<App runtime={createRuntime(core.launch, core.fetch)} />);
  await screen.findByRole("heading", { name: "Who's learning?" });
  fireEvent.click(screen.getByRole("button", { name: /^Ada/ }));
  return screen.findByRole("navigation", { name: "Main" });
}

const planCard = () => screen.findByRole("region", { name: /^Next up/ });
const answers = (core: FakeProfileCore) => core.log.filter((r) => r.method === "POST" && /^\/v1\/cards\/req_/.test(r.path)).map((r) => r.body);

describe("UXS-12", () => {
  test("uxs12_home_before_model", async () => {
    // The tutor model is still loading the whole time: Home and its plan do not wait for it.
    const core = fakeCore((c) => {
      c.health = { status: "starting", components: { core: "ok", runtime: "starting" }, readiness: "model_loading", model_load_progress: 0.62 };
    });
    const started = performance.now();
    await launch(core);
    const card = await planCard();
    expect(performance.now() - started).toBeLessThanOrEqual(CLIENT_KEYS.ui_home_usable_ms);
    expect(core.health.readiness).toBe("model_loading");
    // The next activity first with its estimate and Start; the rest optional; the streak at the foot, said neutrally.
    const rows = within(card).getAllByRole("listitem");
    expect(rows[0]!.textContent).toContain("Warm-up: 2 reviews");
    expect(rows[0]!.textContent).toContain("~5 min");
    expect(within(rows[0]!).getByRole("button", { name: "Start" })).toBeTruthy();
    expect(rows[1]!.textContent).toContain("Optional");
    expect(card.textContent).toContain("Streak 5 days · 1 freeze saved");
    // The plan was asked for with no model and no session turn; the Ask box says the tutor is warming up.
    expect(core.log.some((r) => r.method === "POST" && r.path === "/v1/plans")).toBe(true);
    expect(core.turnsStarted).toBe(0);
    await waitFor(() => expect(document.querySelector("[data-placeholder='Tutor warming up · 62%'], [placeholder='Tutor warming up · 62%']")
      ?? document.body.innerHTML.includes("Tutor warming up · 62%")).toBeTruthy());
    expect(document.body.textContent).not.toMatch(/\bPIN\b|daily limit|minutes left/i);
  });

  test("uxs12_queue_question_until_ready", async () => {
    const core = fakeCore((c) => {
      c.health = { status: "starting", components: { core: "ok", runtime: "starting" }, readiness: "model_loading", model_load_progress: 0.3 };
    });
    const nav = await launch(core);
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    const ask = await waitFor(() => {
      const box = document.querySelector<HTMLElement>("[contenteditable='true']");
      expect(box).not.toBeNull();
      return box!;
    });
    const question = "A car speeds up from 4 m/s to 10 m/s in 3 s. What is its acceleration?";
    fireEvent.paste(ask, { clipboardData: { getData: (type: string) => (type === "text/plain" ? question : "") } });
    await waitFor(() => expect(ask.textContent).toContain("A car speeds up"));
    fireEvent.keyDown(ask, { key: "Enter" });
    // Kept, not sent: the box empties, Home says the question waits for the tutor, and no turn starts yet.
    await screen.findByText("Your question is kept and goes to the tutor as soon as it's ready.");
    await new Promise((resolve) => setTimeout(resolve, CLIENT_KEYS.ui_health_poll_ms + 200));
    expect(core.turnsStarted).toBe(0);
    expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    // The model finishes loading: the question goes by itself, once, and the tutor opens.
    core.health = { status: "ok", components: { core: "ok", runtime: "ok" }, readiness: "ready" };
    await waitFor(() => expect(core.turnsStarted).toBe(1), { timeout: CLIENT_KEYS.ui_health_poll_ms * 4 });
    const turn = core.log.find((r) => r.method === "POST" && r.path.endsWith("/turns"));
    expect(JSON.stringify(turn?.body)).toContain("A car speeds up");
    expect((turn?.body as { intent: string }).intent).toBe("ask");
    await waitFor(() => expect(within(nav).getByRole("button", { name: "Home" }).getAttribute("aria-current")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(core.turnsStarted).toBe(1);
  });

  test("test_uxs12_keep_learning_on_home", async () => {
    // The screen's side of uxs12_keep_learning_without_time_limit (the core's is in test_m15d_plans.py) and LRN-31's
    // card: Change offers the ranked alternatives and a shorter plan, Not today asks nothing further, Start opens the
    // next activity, a stopped plan resumes, and a finished plan offers Keep learning, at any hour, with no PIN.
    const core = fakeCore((c) => {
      c.practiceItems = ITEMS;
    });
    const nav = await launch(core);
    let card = await planCard();
    fireEvent.click(within(card).getByRole("button", { name: "Change" }));
    const swap = await within(card).findAllByRole("button", { name: /min$/ });
    expect(swap).toHaveLength(3);
    fireEvent.click(swap[1]!);
    await waitFor(() => expect(answers(core)).toHaveLength(1));
    expect(answers(core)[0]).toMatchObject({ answer: { action: "change", option_ids: ["alt_1"] } });
    await waitFor(() => expect(core.plans.filter((p) => p.status === "changed")).toHaveLength(1));
    // The changed plan is a new proposal: "Not today" sets it aside and asks nothing more; learning stays open.
    card = await planCard();
    await waitFor(() => expect(within(card).getByRole("button", { name: "Not today" })).toBeTruthy());
    fireEvent.click(within(card).getByRole("button", { name: "Not today" }));
    await screen.findByText("Set aside for today. Lessons, practice and the tutor are all still here.");
    expect(answers(core)[1]).toMatchObject({ answer: { skipped: true } });
    expect(screen.queryByRole("dialog")).toBeNull();
    // Another plan on request, then Start: the card is answered and the first activity (reviews) opens as practice.
    fireEvent.click(screen.getByRole("button", { name: "Show me a plan" }));
    card = await planCard();
    fireEvent.click(await within(card).findByRole("button", { name: "Start" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    expect(answers(core)[2]).toMatchObject({ answer: { action: "start" } });
    expect(core.log.filter((r) => r.path === "/v1/practice/sets").at(-1)?.body).toMatchObject({ subject: "physics", source: "topic", kc_ids: ["kc.phy.o.motion.speed", "kc.phy.o.motion.velocity"] });
    // Stopped after the reviews: back on Home the plan ticks them and continues at the next activity.
    core.finishFirstBlock();
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    card = await planCard();
    await waitFor(() => expect(within(card).getByRole("button", { name: "Continue" })).toBeTruthy());
    expect(card.querySelector("[data-block-status='done']")?.textContent).toContain("Done");
    // Finished: Keep learning proposes a fresh plan and starts it, once, even though Home re-reads the plan.
    core.finishPlan();
    fireEvent.click(within(nav).getByRole("button", { name: "Lessons" }));
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    card = await planCard();
    fireEvent.click(await within(card).findByRole("button", { name: "Keep learning" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    expect(core.plans.filter((p) => p.keep_learning)).toHaveLength(1);
    expect(core.plans.at(-1)?.status).toBe("started");
    expect(core.planAnswers).toEqual(["change:alt_1", "skipped", "start", "start"]);
    expect(document.body.textContent).not.toMatch(/\bPIN\b/);
  });
});

describe("LRN-34", () => {
  test("lrn34_bar_latency", async () => {
    // A checked answer moves the idea's bar (a band, never a decimal) within the LRN-34 budget of the core's verdict.
    let replied = 0;
    const core = fakeCore((c) => {
      c.practiceItems = ITEMS;
      c.mark = () => ({ verdict: "correct", category: null });
      const real = c.fetch;
      c.fetch = async (input, init) => {
        const reply = await real(input, init);
        if (String(input).endsWith("/answers")) replied = performance.now();
        return reply;
      };
    });
    const nav = await launch(core);
    fireEvent.click(within(nav).getByRole("button", { name: "Practice" }));
    await screen.findByRole("heading", { level: 1, name: "Today's practice" });
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "1.2" } });
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "m/s" } });
    fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
    const bar = await screen.findByRole("img", { name: "This idea: Secure" });
    expect(replied).toBeGreaterThan(0);
    expect(performance.now() - replied).toBeLessThanOrEqual(CLIENT_KEYS.ui_mastery_refresh_ms);
    // The bar is the three bands filled up to the idea's band, with the band's word; no number between 0 and 1.
    expect(bar.getAttribute("data-band-bar")).toBe("secure");
    expect(bar.querySelectorAll("[data-filled]")).toHaveLength(3);
    expect(bar.parentElement?.textContent).not.toMatch(/0\.\d/);
  });
});

describe("UXS-27", () => {
  test("test_uxs27_progress_place", async () => {
    const core = fakeCore();
    const nav = await launch(core);
    await screen.findByRole("heading", { level: 1, name: /^Ready to learn, Ada\?$/ });
    // Ctrl+5 opens Progress (TABLE LOC-12a); the sidebar marks it.
    fireEvent.keyDown(window, { key: "5", code: "Digit5", ctrlKey: true });
    await screen.findByRole("heading", { level: 1, name: "Progress" });
    expect(within(nav).getByRole("button", { name: "Progress" }).getAttribute("aria-current")).toBe("page");
    const subject = await screen.findByRole("region", { name: "Physics" });
    // The words of the mastery scale, never a probability; the topics secure; the streak said neutrally.
    expect(subject.textContent).toContain("2 of 7 ideas secure · 0 of 2 topics secure");
    expect(subject.textContent).toContain("2 Secure · 4 Learning · 1 Not started");
    expect(document.body.textContent).toContain("5 days");
    expect(document.body.textContent).toContain("1 freeze saved");
    expect(document.body.textContent).not.toMatch(/\b0\.\d+\b/);
    // Every idea a heat-map cell with its state word as its name (DSN-23).
    for (const word of ["Secure", "Refresh due", "Learning", "Nearly secure", "Not started", "Coming back to this"]) {
      expect(within(subject).getAllByRole("listitem", { name: word }).length, word).toBeGreaterThan(0);
    }
    // No grade band: the core says this pack sets no exam board letters (`no_scale`, D27), so not even the estimate
    // line shows.
    expect(subject.querySelector("[data-grade]")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Likely band|grade estimate/);
    // Mastery over time as a chart with its table alternative and summary (LOC-16).
    expect(subject.textContent).toContain("Secure ideas went from 0 to 2 over 3 weeks.");
    fireEvent.click(within(subject).getByRole("button", { name: "Show as table" }));
    const table = within(subject).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getAllByRole("row")[3]!.textContent).toMatch(/42$/);
    // "What your tutor knows" opens from here and leads back.
    fireEvent.click(screen.getByRole("button", { name: "What your tutor knows" }));
    await screen.findByRole("heading", { name: "What the tutor knows about you" });
  });

  test("test_uxs27_no_band_without_board_letters", async () => {
    // D27 (D100): the core says `no_scale` for a pack that sets no exam board letters (every pack today; proposed in
    // contract-additions-grade-bands.json): no band, no range, no estimate line, whatever the checked answers.
    for (const grade of [{ status: "no_scale", checked: 40, needed: 30 }, { status: "no_scale", checked: 3, needed: 30 }]) {
      const core = fakeCore((c) => { c.progress = progressView(grade); });
      await launch(core);
      fireEvent.keyDown(window, { key: "5", code: "Digit5", ctrlKey: true });
      const subject = await screen.findByRole("region", { name: "Physics" });
      expect(subject.querySelector("[data-grade]")).toBeNull();
      expect(document.body.textContent).not.toMatch(/Likely band|grade estimate|enough evidence/);
      cleanup();
    }
  });
});

describe("UXS-51", () => {
  test("test_uxs51_search_where_no_tutor_answers", async () => {
    const solution = {
      worked_example_id: "itm.phy.o.motion.0101", problem: "Synthetic: a trolley moves 12 m in 4 s. Find its average speed.",
      steps: [{ n: 1, latex: "v = \\frac{d}{t}", reason: "Speed is distance over time", check_id: null }, { n: 2, latex: "v = \\frac{12}{4} = 3", reason: "Substitute", check_id: "chk_1" }],
      final_answer: { latex: "3\\,\\text{m/s}", check_id: "chk_1" }, faded_steps: [],
    };
    const core = fakeCore((c) => {
      c.models = STATES.find((s) => s.id === "first-run-tutor.canonical.content-only")!.payload as unknown as ModelCatalogue;
      c.searchItems = [
        { ...ITEMS[0]!, item_id: "itm.phy.o.motion.0101", stem: "Synthetic: a trolley moves 12 m in 4 s. Find its average speed.", kc_ids: ["kc.phy.o.motion.speed"], solution },
        { ...ITEMS[0]!, item_id: "itm.phy.o.motion.0102", stem: "Synthetic: a trolley on the mock paper moves 9 m.", kc_ids: ["kc.phy.o.motion.speed"], reserved: true },
      ];
    });
    const nav = await launch(core);
    fireEvent.click(within(nav).getByRole("button", { name: "Home" }));
    const box = await screen.findByRole("search", { name: "Worked solutions" });
    // Photos need the tutor: the photo action says so.
    fireEvent.click(within(box).getByRole("button", { name: "Photo of a question" }));
    expect(box.textContent).toContain("Reading photos needs the tutor. Type the question instead.");
    fireEvent.change(within(box).getByRole("searchbox", { name: "Search worked solutions" }), { target: { value: "trolley speed" } });
    fireEvent.click(within(box).getByRole("button", { name: "Search" }));
    const results = await screen.findByRole("region", { name: "1 match" });
    expect(core.searches).toEqual(["trolley speed"]);
    const match = within(results).getByRole("button");
    expect(match.textContent).toContain("Matches: trolley, speed");
    expect(Array.from(match.querySelectorAll("mark")).map((m) => m.textContent)).toEqual(["trolley", "speed"]);
    expect(results.textContent).not.toContain("mock paper");
    // Opened: the question, then its full solution on request, a step at a time or all at once, with no attempt.
    fireEvent.click(match);
    fireEvent.click(await screen.findByRole("button", { name: "Show solution" }));
    const steps = await screen.findByRole("list", { name: "Worked solution" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    await waitFor(() => expect(within(steps).getAllByRole("listitem")).toHaveLength(2));
    expect(core.solutionsRead).toEqual(["itm.phy.o.motion.0101"]);
    expect(core.log.some((r) => r.path.includes("/practice/sets") && r.method === "POST")).toBe(false);
    // Nothing matches: what to try next and the way to the topics.
    fireEvent.click(screen.getByRole("button", { name: "Back to results" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search worked solutions" }), { target: { value: "titration" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText("No worked solution matches. Try fewer words, or open the topic's lesson.");
    fireEvent.click(screen.getByRole("button", { name: "Browse topics" }));
    await waitFor(() => expect(within(nav).getByRole("button", { name: "Lessons" }).getAttribute("aria-current")).toBe("page"));
  });
});

describe("PRM-03", () => {
  test("test_prm03_tutor_name_and_picture", async () => {
    const core = fakeCore((c) => {
      for (const s of c.settings.values()) Object.assign(s, { tutor_name: "Jana", tutor_avatar: "avatar.jana" });
    });
    await launch(core);
    fireEvent.click(menuItem("Settings"));
    const section = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-settings-section='tutor']");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(section.textContent).toContain("Your tutor is called Jana.");
    // The one pick (UXS-54): a name of the student's own, then another character, which keeps that name.
    fireEvent.change(within(section).getByRole("textbox", { name: "Your tutor's name" }), { target: { value: "Ama" } });
    fireEvent.click(within(section).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(section.textContent).toContain("Your tutor is called Ama."));
    fireEvent.click(within(section).getByRole("radio", { name: "Pebble" }));
    expect((within(section).getByRole("textbox", { name: "Your tutor's name" }) as HTMLInputElement).value).toBe("Ama");
    fireEvent.click(within(section).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(section.querySelector("svg[data-character='avatar.pebble']")).not.toBeNull());
    expect((within(section).getByRole("radio", { name: "Pebble" }) as HTMLInputElement).checked).toBe(true);
    const patches = core.log.filter((r) => r.method === "PATCH" && r.path.endsWith("/settings")).map((r) => r.body);
    expect(patches).toEqual([{ tutor_avatar: "avatar.jana", tutor_name: "Ama" }, { tutor_avatar: "avatar.pebble", tutor_name: "Ama" }]);
    // Kept per profile: the settings the core holds for Ada, and only hers.
    const [ada, other] = [...core.settings.values()];
    expect(ada).toMatchObject({ tutor_name: "Ama", tutor_avatar: "avatar.pebble" });
    expect(other).toMatchObject({ tutor_name: "Jana", tutor_avatar: "avatar.jana" });
    // Back to Jana, character and name, in one step.
    fireEvent.click(within(section).getByRole("button", { name: "Reset to Jana" }));
    await waitFor(() => expect(section.textContent).toContain("Your tutor is called Jana."));
    expect(core.log.filter((r) => r.method === "PATCH" && r.path.endsWith("/settings")).at(-1)?.body).toEqual({ tutor_avatar: "avatar.jana", tutor_name: "Jana" });
  });
});
