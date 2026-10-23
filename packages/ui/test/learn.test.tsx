// UXS-22, UXS-23, UXS-16, DSN-04, UIA keyboard and screen-reader rules, and UXS-10's tutor step in the UI. The subject
// map shows a mastery change on its tile within the UXS-22 budget, every state as pattern, icon and word, and a topic
// sheet that opens from the keyboard, takes focus and gives it back; the lesson player moves part by part with focus
// on each part's heading, saves the position, marks checks with an icon and a word (never "wrong") and offers "Ask
// about this" only when a tutor can answer; first run's tutor step names the figure that is short. Against the fake
// core, with the gallery's own fixtures (built from the repository's curriculum sources).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test } from "vitest";
import { CLIENT_KEYS, LessonController, ProfileController, StoreHolder, SubjectMapController, subjectMapProblems, tutorSetup, type MapKc, type SubjectMap as Map } from "@jana/client-core";
import type { ModelCatalogue } from "@jana/contracts-ts";
import { FakeProfileCore, PROFILES } from "../../client-core/test/profilecore.js";
import { STATES } from "../gallery/index.js";
import { LocaleProvider } from "../src/i18n.js";
import { LessonPlayer } from "../src/learn/LessonPlayer.js";
import { SubjectMap, SubjectMapContent } from "../src/learn/SubjectMap.js";
import { RegistryProvider } from "../src/registry/registry.js";
import { FirstRunTutor } from "../src/setup/FirstRunTutor.js";
import { defaultRegistry } from "../src/transcript/parts.js";

const BEN = PROFILES[1]!;
const payload = <T,>(id: string) => STATES.find((s) => s.id === id)!.payload as T;
const MAP = payload<{ map: Map }>("subject-map.canonical.topic-sheet").map;
const LESSON = payload<{ lesson: Record<string, unknown> & { lesson_id: string; blocks: { type: string }[] } }>("lesson-player.canonical").lesson;
const TOPIC = MAP.sections[0]!.topics[0]!;

afterEach(() => cleanup());

function wrap(children: ReactNode) {
  return (
    <LocaleProvider locale="en">
      <RegistryProvider registry={defaultRegistry()}>{children}</RegistryProvider>
    </LocaleProvider>
  );
}

async function unlocked() {
  const core = new FakeProfileCore();
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  return { core, profiles };
}

function withStates(map: Map, state: (kc: MapKc) => MapKc["state"]): Map {
  const band = { not_started: "not_started", learning: "learning", ready_to_check: "learning", moved_on: "learning", mastered: "secure", needs_review: "secure" } as const;
  return { ...map, sections: map.sections.map((s) => ({ ...s, topics: s.topics.map((t) => ({ ...t, kcs: t.kcs.map((k) => ({ ...k, state: state(k), band: band[state(k)] })) })) })) };
}

const tile = () => document.querySelector<HTMLButtonElement>(`[data-topic-id="${TOPIC.node_id}"]`)!;

describe("UXS-22", () => {
  test("uxs22_mastery_refresh", async () => {
    const { core, profiles } = await unlocked();
    core.maps.set(MAP.subject_id, MAP);
    const controller = new SubjectMapController(profiles);
    render(wrap(<SubjectMap controller={controller} subjectId={MAP.subject_id} />));
    await waitFor(() => expect(tile()).not.toBeNull());
    expect(tile().getAttribute("data-label")).toBe("needs_review"); // a KC is refresh due: the first row of TABLE UXS-22a
    expect(within(tile()).getByText("Refresh due")).toBeTruthy();

    // The tutor marks the student's last KCs secure: progress.update reaches the map and the tile follows.
    core.maps.set(MAP.subject_id, withStates(MAP, () => "mastered"));
    const started = performance.now();
    act(() => controller.onProgress(TOPIC.kcs[0]!.kc_id));
    await waitFor(() => expect(tile().getAttribute("data-label")).toBe("mastered"), { timeout: CLIENT_KEYS.ui_mastery_refresh_ms, interval: 5 });
    expect(performance.now() - started).toBeLessThan(CLIENT_KEYS.ui_mastery_refresh_ms);
    expect(within(tile()).getByText("Secure")).toBeTruthy();
    expect(within(tile()).getByText(`${TOPIC.kcs.length} Secure`)).toBeTruthy();
  });

  test("uxs22_filter_by_syllabus", async () => {
    // CUR-06 (D113): "All topics" first; choosing Cambridge 4024 hides calculus (outside it) and shows each tile's
    // codes; the not-endorsed line names the board; the choice survives a re-read and a remount while the app is open.
    const syllabusMap = payload<{ map: Map }>("subject-map.canonical.syllabus").map;
    expect(subjectMapProblems(syllabusMap)).toEqual([]);
    const { core, profiles } = await unlocked();
    core.maps.set(syllabusMap.subject_id, syllabusMap);
    const controller = new SubjectMapController(profiles);
    const { unmount } = render(wrap(<SubjectMap controller={controller} subjectId={syllabusMap.subject_id} />));
    const calculus = () => document.querySelector("[data-section-id='cur.mth.o.calculus']");
    await waitFor(() => expect(calculus()).not.toBeNull());
    expect(document.querySelector("[data-syllabus-switch]")!.getAttribute("data-syllabus-switch")).toBe("-all");
    expect(document.querySelector("[data-syllabus-codes]")).toBeNull();
    expect(screen.getByText("Not endorsed by Cambridge.")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "Cambridge 4024" }));
    expect(calculus()).toBeNull();
    const first = syllabusMap.sections[0]!.topics[0]!;
    const card = document.querySelector<HTMLButtonElement>(`[data-topic-id="${first.node_id}"]`)!;
    const codes = first.syllabus_points!.filter((p) => p.scheme === "cambridge_4024").map((p) => p.code);
    expect(within(card).getByText(`4024 · ${codes.join(", ")}`)).toBeTruthy();
    for (const tile of document.querySelectorAll("[data-topic-id]")) expect(tile.querySelector("[data-syllabus-codes]")).not.toBeNull();
    expect(screen.getByText("Not endorsed by Cambridge.")).toBeTruthy();

    // The sheet lists the topic's points by syllabus.
    fireEvent.click(card);
    const sheet = document.querySelector("[data-topic-sheet]")!;
    expect(within(sheet as HTMLElement).getByText("Syllabus points")).toBeTruthy();
    expect(within(sheet as HTMLElement).getByText(`Cambridge 4024 · ${codes[0]}`, { exact: false })).toBeTruthy();

    unmount();
    render(wrap(<SubjectMap controller={controller} subjectId={syllabusMap.subject_id} />));
    await waitFor(() => expect(document.querySelector("[data-syllabus-switch]")?.getAttribute("data-syllabus-switch")).toBe("cambridge_4024"));
    expect(calculus()).toBeNull();
    act(() => controller.chooseSyllabus(null));
    expect(calculus()).not.toBeNull();
  });

  test("map_states_are_pattern_icon_and_word", () => {
    const state = STATES.find((s) => s.id === "subject-map.canonical")!;
    const map = (state.payload as { map: Map }).map;
    render(wrap(<SubjectMapContent view={{ status: "ready", subjectId: map.subject_id, map }} />));
    const marks = [...document.querySelectorAll("[data-mastery]")];
    expect(new Set(marks.map((m) => m.getAttribute("data-mastery"))).size).toBeGreaterThanOrEqual(4);
    for (const mark of marks) {
      expect(mark.querySelector("svg"), mark.outerHTML).not.toBeNull();
      expect(mark.className).toMatch(/mastery-pattern-(none|solid|dots-sparse|dots-dense|hatch-diagonal|cross-hatch)/);
      expect((mark.textContent ?? "").trim()).not.toBe("");
    }
    // Sections are headed by the syllabus section, tiles are buttons named by their words.
    expect(screen.getByRole("heading", { level: 2, name: map.sections[0]!.title })).toBeTruthy();
    for (const button of document.querySelectorAll("[data-topic-id]")) expect(button.tagName).toBe("BUTTON");
  });

  test("test_uxs22_untouched_topic_says_not_started_once", () => {
    // A topic nobody has started says so once, with its mark: no "4 Not started" count line, no empty bar or ring, and
    // no "0 lessons". Once a KC moves, the counts, the bar and the ring appear, and a lesson count only when there are lessons.
    const fresh = withStates(MAP, () => "not_started");
    const topic = { ...fresh.sections[0]!.topics[0]!, lessons: [] };
    const map = { ...fresh, sections: [{ ...fresh.sections[0]!, topics: [topic] }] };
    const { unmount } = render(wrap(<SubjectMapContent view={{ status: "ready", subjectId: map.subject_id, map }} />));
    const card = tile();
    expect(within(card).getAllByText("Not started")).toHaveLength(1);
    expect(card.querySelector("[data-mastery='not_started']")).not.toBeNull();
    expect(card.querySelector("[data-segments]")).toBeNull();
    expect(card.querySelector("[data-mastery-ring]")).toBeNull();
    expect(card.textContent).not.toMatch(/\d+ Not started|lessons?\b/);
    unmount();
    const moving = withStates(MAP, (kc) => (kc.kc_id === TOPIC.kcs[0]!.kc_id ? "learning" : "not_started"));
    render(wrap(<SubjectMapContent view={{ status: "ready", subjectId: moving.subject_id, map: moving }} />));
    expect(tile().querySelector("[data-segments]")).not.toBeNull();
    expect(tile().querySelector("[data-mastery-ring]")).not.toBeNull();
    expect(tile().textContent).toContain("1 Learning");
    expect(tile().textContent).toMatch(new RegExp(`${TOPIC.lessons.length} lessons?`));
  });

  test("topic_sheet_keyboard_and_actions", async () => {
    const { core, profiles } = await unlocked();
    core.maps.set(MAP.subject_id, MAP);
    const controller = new SubjectMapController(profiles);
    const started: string[] = [];
    const checks: [string, boolean][] = [];
    render(wrap(<SubjectMap controller={controller} subjectId={MAP.subject_id} actions={{ onStartLesson: (id) => started.push(id), onMasteryCheck: (kc, now) => checks.push([kc.kc_id, now]) }} />));
    await waitFor(() => expect(tile()).not.toBeNull());
    tile().focus();
    fireEvent.click(tile());
    const sheet = await screen.findByRole("dialog", { name: TOPIC.title });
    expect(document.activeElement).toBe(within(sheet).getByRole("heading", { name: TOPIC.title }));
    expect(tile().getAttribute("aria-expanded")).toBe("true");

    // Every KC with its own label; "Check my mastery" only on the nearly secure KC, "I already know this" on every KC
    // that is not secure; no practice or tutor action without a handler.
    const rows = [...sheet.querySelectorAll("li[data-kc-id]")];
    expect(rows).toHaveLength(TOPIC.kcs.length);
    for (const row of rows) {
      const state = row.getAttribute("data-state");
      expect(!!within(row as HTMLElement).queryByRole("button", { name: "Check my mastery" })).toBe(state === "ready_to_check");
      expect(!!within(row as HTMLElement).queryByRole("button", { name: "I already know this" })).toBe(state !== "mastered");
    }
    expect(within(sheet).queryByRole("button", { name: "Practise this" })).toBeNull();
    expect(within(sheet).queryByRole("button", { name: "Ask the tutor about this" })).toBeNull();
    fireEvent.click(within(sheet).getByRole("button", { name: /Start the lesson/ }));
    expect(started).toEqual([TOPIC.lessons[0]!.lesson_id]);
    const nearly = rows.find((r) => r.getAttribute("data-state") === "ready_to_check")!;
    fireEvent.click(within(nearly as HTMLElement).getByRole("button", { name: "Check my mastery" }));
    expect(checks).toEqual([[nearly.getAttribute("data-kc-id"), false]]);

    fireEvent.keyDown(sheet, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(tile());
  });

  test("map_empty_and_failed_states", async () => {
    const { core, profiles } = await unlocked();
    core.maps.set("cur.chm.o", { ...MAP, subject_id: "cur.chm.o", subject: "chemistry", status: "not_installed", pack: null, sections: [] });
    const controller = new SubjectMapController(profiles);
    const view = render(wrap(<SubjectMap controller={controller} subjectId="cur.chm.o" />));
    await screen.findByText(/isn't on this computer yet/);
    view.unmount();
    core.unavailable.add("/v1/curriculum/cur.mth.o/map");
    render(wrap(<SubjectMap controller={new SubjectMapController(profiles)} subjectId="cur.mth.o" />));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("progress is still saved");
    core.unavailable.clear();
    core.maps.set("cur.mth.o", { ...MAP, subject_id: "cur.mth.o", subject: "mathematics" });
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(tile()).not.toBeNull());
  });
});

describe("UXS-23 and UXS-16", () => {
  async function player(onAsk?: () => void) {
    const { core, profiles } = await unlocked();
    core.lessons.set(LESSON.lesson_id, LESSON);
    const controller = new LessonController(profiles);
    render(wrap(<LessonPlayer controller={controller} lessonId={LESSON.lesson_id} {...(onAsk !== undefined ? { onAsk } : {})} />));
    await screen.findByRole("heading", { level: 2, name: "Before you start" });
    return { core, controller };
  }

  test("test_uxs23_next_back_focus_and_position", async () => {
    const { core } = await player();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    const idea = await screen.findByRole("heading", { level: 2, name: "The idea" });
    await waitFor(() => expect(document.activeElement).toBe(idea));
    expect(screen.getByText("Part 2 of 8")).toBeTruthy();
    await waitFor(() => expect(core.log.filter((l) => l.method === "PUT").map((l) => l.body)).toEqual([{ block_index: 1, lesson_version: LESSON.version }]));
    // The parts list jumps straight to a part and marks the current one.
    const parts = screen.getByRole("navigation", { name: "Lesson parts" });
    fireEvent.click(within(parts).getByRole("button", { name: "Summary" }));
    await screen.findByRole("heading", { level: 2, name: "Summary" });
    expect(within(parts).getByRole("button", { name: "Summary" }).getAttribute("aria-current")).toBe("step");
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    await screen.findByText(/You've finished this lesson/);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await screen.findByRole("heading", { level: 2, name: "Summary" });
  });

  test("test_uxs16_check_feedback_icon_and_word", async () => {
    const { core } = await player(() => undefined);
    core.mark = (itemId) => (itemId === "itm.phy.o.motion.0022" ? { verdict: "correct", category: null } : { verdict: "incorrect", category: "power_of_ten" });
    fireEvent.click(within(screen.getByRole("navigation", { name: "Lesson parts" })).getByRole("button", { name: "Quick check" }));
    await screen.findByRole("heading", { level: 2, name: "Quick check" });
    const [first, second] = [...document.querySelectorAll<HTMLElement>("article[data-item-id]")];
    for (const [article, value] of [[first!, "1.2"], [second!, "300"]] as const) {
      const answer = within(article).getByLabelText("Your answer");
      fireEvent.change(answer, { target: { value } });
      fireEvent.change(within(article).getByLabelText("Unit"), { target: { value: "m/s" } });
      fireEvent.click(within(article).getByRole("button", { name: "Check my answer" }));
    }
    await waitFor(() => expect(document.querySelectorAll("[data-verdict]")).toHaveLength(2));
    const right = first!.querySelector("[data-verdict]")!;
    const off = second!.querySelector("[data-verdict]")!;
    expect(right.querySelector("svg")).not.toBeNull();
    expect(right.textContent).toContain("Correct");
    expect(off.querySelector("svg")).not.toBeNull();
    expect(off.textContent).toContain("Not quite");
    expect(off.textContent).toContain("power of ten");
    expect(document.body.textContent?.toLowerCase()).not.toContain("wrong");
    expect(core.log.filter((l) => l.path.endsWith("/checks")).map((l) => (l.body as { answer: unknown }).answer)).toEqual([
      { parts: [{ part_id: "a", kind: "numeric", value: "1.2", unit: "m/s" }] },
      { parts: [{ part_id: "a", kind: "numeric", value: "300", unit: "m/s" }] },
    ]);
    expect(screen.getByRole("button", { name: "Ask about this" })).toBeTruthy();
  });

  test("test_uxs23_content_only_offers_no_tutor", async () => {
    await player();
    expect(screen.queryByRole("button", { name: "Ask about this" })).toBeNull();
    const article = document.querySelector<HTMLElement>("article[data-item-id]")!;
    expect(within(article).getByRole("button", { name: "Check my answer" }).hasAttribute("disabled")).toBe(true); // nothing to check yet
  });
});

describe("UXS-23 step-shape lessons (D110)", () => {
  const STEPS = payload<{ lesson: Record<string, unknown> & { lesson_id: string; version: string; blocks: { type: string; items: { item_id: string }[] }[] } }>("lesson-player.canonical.step").lesson;
  const FIRST = STEPS.blocks[0]!.items[0]!.item_id;

  async function stepPlayer() {
    const { core, profiles } = await unlocked();
    core.lessons.set(STEPS.lesson_id, STEPS);
    const controller = new LessonController(profiles);
    render(wrap(<LessonPlayer controller={controller} lessonId={STEPS.lesson_id} onClose={() => undefined} />));
    await screen.findByRole("heading", { level: 1, name: /A price of \$450 is increased by 20%/ });
    return { core };
  }
  const checks = (core: { log: { path: string; body: unknown }[] }) => core.log.filter((l) => l.path.endsWith("/checks")).map((l) => l.body as { item_id: string; attempt?: number });

  test("test_uxs23_step_retry_then_shown_in_the_player", async () => {
    const { core } = await stepPlayer();
    expect(screen.getByText(/Try it first/)).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuetext")).toBe("Step 1 of 5, then a check");
    expect(screen.getByRole("button", { name: "Leave the lesson" })).toBeTruthy();
    const check = screen.getByRole("button", { name: "Check" });
    expect(check.hasAttribute("disabled")).toBe(true); // every step asks for an action first
    expect(screen.queryByRole("button", { name: /Continue/ })).toBeNull();

    // First miss: where to look and a retry, never the why or the working.
    core.mark = () => ({ verdict: "incorrect", category: "value" });
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "470" } });
    fireEvent.click(check);
    await screen.findByText("Not quite. Have another go.");
    expect(screen.getByText("Look here")).toBeTruthy();
    expect(document.querySelector("[data-why]")).toBeNull();
    expect(document.body.textContent?.toLowerCase()).not.toContain("wrong");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect((screen.getByLabelText("Your answer") as HTMLInputElement).value).toBe("470"); // the draft is kept

    // Second miss: the step is shown with its working, and the lesson moves on.
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(document.querySelector("[data-why][data-shown]")).not.toBeNull());
    expect(document.querySelector('[data-answer-state="look_here"]')?.textContent).toContain("Shown");
    expect(screen.getByText(/doesn't count against you/)).toBeTruthy();
    expect(checks(core).map((b) => [b.item_id, b.attempt])).toEqual([[FIRST, 1], [FIRST, 2]]);

    // A correct answer: Checked beside the why; Continue moves on with focus on the next question.
    core.mark = () => ({ verdict: "correct", category: null });
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    const next = await screen.findByRole("heading", { level: 1, name: /A price of \$360 is increased by 12%/ });
    await waitFor(() => expect(document.activeElement).toBe(next));
    expect(screen.getByRole("progressbar").getAttribute("aria-valuetext")).toBe("Step 2 of 5, then a check");
    fireEvent.click(screen.getAllByRole("radio")[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(document.querySelector('[data-answer-state="checked"]')?.textContent).toContain("Checked"));
    expect(screen.getByText("A synthetic why for this step.")).toBeTruthy();
    expect(screen.getByText("Next, you'll calculate")).toBeTruthy();
    await waitFor(() => expect(core.log.filter((l) => l.method === "PUT").map((l) => l.body)).toEqual([{ block_index: 1, lesson_version: STEPS.version }]));
  });

  test("test_uxs23_step_lesson_check_then_finish", async () => {
    const { core } = await stepPlayer();
    core.mark = () => ({ verdict: "correct", category: null });
    const answer = async () => {
      const value = screen.queryByLabelText("Your answer");
      if (value !== null) fireEvent.change(value, { target: { value: "1" } });
      else fireEvent.click(screen.getAllByRole("radio")[0]!);
      fireEvent.click(screen.getByRole("button", { name: "Check" }));
      await waitFor(() => expect(document.querySelector('[data-answer-state="checked"]')).not.toBeNull());
    };
    for (let step = 0; step < 5; step++) {
      await answer();
      fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
      await waitFor(() => expect(document.querySelector("[data-answer-state]")).toBeNull());
    }
    expect(screen.getByRole("progressbar").getAttribute("aria-valuetext")).toBe("The check: question 1 of 3");
    for (let question = 0; question < 3; question++) {
      expect(screen.getByText(new RegExp(`Check · question ${question + 1} of 3`))).toBeTruthy();
      await answer();
      fireEvent.click(screen.getByRole("button", { name: question === 2 ? "Finish" : /Continue/ }));
      if (question < 2) await waitFor(() => expect(document.querySelector("[data-answer-state]")).toBeNull());
    }
    await screen.findByText(/You've finished this lesson/);
    expect(checks(core)).toHaveLength(8);
    expect(checks(core).every((b) => b.attempt === 1)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await screen.findByText(/Check · question 3 of 3/);
  });
});

describe("UXS-10 and PLT-29", () => {
  test("first_run_tutor_step_names_the_short_figure", () => {
    const below = STATES.find((s) => s.id === "first-run-tutor.canonical.below-minimum")!.payload as unknown as ModelCatalogue;
    let continued = 0;
    render(wrap(<FirstRunTutor name="Ada" setup={tutorSetup(below)} onContinue={() => (continued += 1)} onOnlineFeatures={() => undefined} />));
    const step = screen.getByRole("region", { name: "You're ready, Ada." });
    expect(step.textContent).toContain("This computer has 4 GB of memory; the tutor needs 8 GB.");
    // The hand-off is not a setup step: no step count (D86: first run has one step).
    expect(step.textContent).not.toMatch(/Step \d of \d/);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "You're ready, Ada." }));
    fireEvent.click(screen.getByRole("button", { name: "Continue without the tutor" }));
    expect(continued).toBe(1);
    expect(screen.getByRole("button", { name: "Online features" })).toBeTruthy();
    expect(tutorSetup(null).kind).toBe("checking");
  });
});
