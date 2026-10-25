// UXS-22, UXS-23, LRN-34 and SEC-19 in the client core: a tile's label follows TABLE UXS-22a (first matching row
// wins) and its bar counts KCs by LRN-34 band; a malformed map, lesson or check reply never reaches a screen; a
// mastery change re-reads the map only when the KC is on it; a lesson opens at its saved position, every move saves
// the position (a failed save never stops the lesson), checks are marked by the core; and locking the profile drops
// the map and the lesson. Against the fake core; the curriculum here is synthetic.
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  KC_STATES, LessonController, ProfileController, StoreHolder, SubjectMapController, bandCounts, checkResultProblems, lessonProblems, subjectId,
  subjectMapProblems, topicLabel, type KcState, type MapKc, type SubjectMap,
} from "../src/index.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const BEN = PROFILES[1]!;
const SUBJECT = "cur.phy.o";
const BANDS: Record<KcState, MapKc["band"]> = {
  not_started: "not_started", learning: "learning", ready_to_check: "learning", moved_on: "learning", mastered: "secure", needs_review: "secure",
};

const kc = (slug: string, state: KcState): MapKc => ({ kc_id: `kc.phy.o.motion.${slug}`, code: `PHY-O-01.02.K${slug.length}`, statement: `Works out the ${slug}`, state, band: BANDS[state] });

function map(states: KcState[]): SubjectMap {
  return {
    subject_id: SUBJECT, subject: "physics", level: "O", title: "Physics", status: "ready", pack: { pack_id: "pack.phy.o", version: "0.1.0" },
    sections: [{ node_id: "cur.phy.o.mechanics", code: "PHY-O-01", title: "Mechanics", topics: [{
      node_id: "cur.phy.o.mechanics.motion", code: "PHY-O-01.02", title: "Motion", kcs: states.map((s, i) => kc(`skill_${i}`, s)),
      lessons: [{ lesson_id: "les.phy.o.mechanics.motion_intro", title: "Speed", estimated_minutes: 10, kc_ids: [`kc.phy.o.motion.skill_0`] }],
    }] }],
  };
}

const item = (n: number) => ({
  item_id: `itm.phy.o.motion.000${n}`, pack_id: "pack.phy.o", pack_version: "0.1.0", kc_ids: ["kc.phy.o.motion.skill_0"], kind: "numeric", stem: `A cart rolls ${n * 10} m.`,
  parts: [{ part_id: "a", prompt: "How far?", marks: 1, uses_parts: [], input: { kind: "numeric", unit_prompt: null } }], visual: null, marks: 1,
});

const LESSON = {
  lesson_id: "les.phy.o.mechanics.motion_intro", node_id: "cur.phy.o.mechanics.motion", title: "Speed", estimated_minutes: 10, kc_ids: ["kc.phy.o.motion.skill_0"],
  version: "0.1.0", pack: { pack_id: "pack.phy.o", version: "0.1.0" },
  blocks: [
    { type: "prior_knowledge", items: [item(1)] },
    { type: "idea", text: "Speed is distance over time.", visual: null },
    { type: "quick_check", items: [item(2), item(3)] },
    { type: "summary", text: "Divide the distance by the time." },
  ],
};

afterEach(() => vi.useRealTimers());

async function unlocked(core = new FakeProfileCore()) {
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(BEN.profile_id)).toBe(true);
  return { core, profiles };
}

describe("UXS-22 and LRN-34", () => {
  test("uxs22a_topic_label_first_matching_row", () => {
    const rows: [KcState[], KcState][] = [
      [["mastered", "needs_review", "moved_on"], "needs_review"], // refresh due wins over everything
      [["mastered", "moved_on", "learning"], "moved_on"],
      [["not_started", "not_started"], "not_started"],
      [["mastered", "mastered"], "mastered"],
      [["ready_to_check", "mastered"], "ready_to_check"],
      [["ready_to_check"], "ready_to_check"],
      [["not_started", "mastered"], "learning"],
      [["learning", "ready_to_check"], "learning"],
    ];
    for (const [states, label] of rows) expect(topicLabel(states), states.join(",")).toBe(label);
    // Every state is a possible label, and a topic always gets exactly one.
    expect(new Set(rows.map(([, l]) => l))).toEqual(new Set(KC_STATES));
  });

  test("test_lrn34_bar_counts_by_band", () => {
    const kcs = (["mastered", "needs_review", "learning", "moved_on", "ready_to_check", "not_started"] as KcState[]).map((s, i) => kc(`k${i}`, s));
    expect(bandCounts(kcs)).toEqual({ secure: 2, learning: 3, not_started: 1 });
  });

  test("replies_are_checked_at_the_boundary", () => {
    expect(subjectMapProblems(map(["learning"]))).toEqual([]);
    expect(subjectMapProblems({ ...map(["learning"]), status: "maybe" })).toEqual(["status"]);
    const probability = map(["learning"]);
    (probability.sections[0]!.topics[0]!.kcs[0] as unknown as Record<string, unknown>).state = 0.83;
    expect(subjectMapProblems(probability)).toEqual(["sections"]);
    expect(lessonProblems({ ...LESSON, position: null })).toEqual([]);
    // A check item that carries its key is not the contract's PracticeItem: the block is refused.
    const leaky = { ...LESSON, position: null, blocks: [{ type: "quick_check", items: [{ ...item(4), answer: "40" }] }] };
    expect(lessonProblems(leaky)).toEqual(["blocks.0"]);
    expect(checkResultProblems({ client_attempt_id: "cli_x", item_id: "i", verdict: "wrong", marks_awarded: 0, marks_total: 1, parts: [] })).toEqual(["verdict", "parts"]);
    expect(subjectId("physics", "O")).toBe("cur.phy.o");
    expect(subjectId("history", "O")).toBeNull();
  });

  test("test_uxs22_progress_rereads_only_its_subject", async () => {
    const { core, profiles } = await unlocked();
    core.maps.set(SUBJECT, map(["learning", "ready_to_check"]));
    const controller = new SubjectMapController(profiles);
    await controller.load(SUBJECT);
    expect(controller.getView().status).toBe("ready");
    const reads = () => core.log.filter((l) => l.path === `/v1/curriculum/${SUBJECT}/map`).length;
    expect(reads()).toBe(1);
    controller.onProgress("kc.chm.o.moles.amount"); // not on this map
    expect(reads()).toBe(1);
    core.maps.set(SUBJECT, map(["mastered", "mastered"]));
    controller.onProgress("kc.phy.o.motion.skill_1");
    await vi.waitFor(() => expect(topicLabel(controller.getView().map!.sections[0]!.topics[0]!.kcs.map((k) => k.state))).toBe("mastered"));
    expect(reads()).toBe(2);
  });

  test("a_failed_or_malformed_map_read_says_so", async () => {
    const { core, profiles } = await unlocked();
    core.maps.set(SUBJECT, { ...map(["learning"]), sections: "lots" });
    const controller = new SubjectMapController(profiles);
    await controller.load(SUBJECT);
    expect(controller.getView()).toMatchObject({ status: "failed", map: null });
    // A re-read that fails keeps the map already shown.
    core.maps.set(SUBJECT, map(["learning"]));
    await controller.load(SUBJECT);
    core.unavailable.add(`/v1/curriculum/${SUBJECT}/map`);
    await controller.load(SUBJECT);
    expect(controller.getView().status).toBe("ready");
    expect(controller.getView().map).not.toBeNull();
  });
});

describe("UXS-23", () => {
  test("test_uxs23_position_saved_and_resumed", async () => {
    const { core, profiles } = await unlocked();
    core.lessons.set(LESSON.lesson_id, LESSON);
    const player = new LessonController(profiles);
    await player.load(LESSON.lesson_id);
    expect(player.getView()).toMatchObject({ status: "ready", index: 0 });
    await player.go(2);
    await player.go(9); // past the end: nothing moves, nothing is saved
    expect(core.log.filter((l) => l.method === "PUT").map((l) => l.body)).toEqual([{ block_index: 2, lesson_version: "0.1.0" }]);
    const again = new LessonController(profiles);
    await again.load(LESSON.lesson_id);
    expect(again.getView().index).toBe(2);
    // A failed save never stops the lesson; it says so and the next move tries again.
    core.positionFails = "core_starting";
    await again.go(3);
    expect(again.getView()).toMatchObject({ index: 3, positionFailed: true });
    core.positionFails = null;
    await again.go(1);
    expect(again.getView()).toMatchObject({ index: 1, positionFailed: false });
  });

  test("checks_are_marked_by_the_core", async () => {
    const { core, profiles } = await unlocked();
    core.lessons.set(LESSON.lesson_id, LESSON);
    core.mark = (itemId) => (itemId.endsWith("0002") ? { verdict: "correct", category: null } : { verdict: "incorrect", category: "unit_error" });
    const player = new LessonController(profiles);
    await player.load(LESSON.lesson_id);
    const right = await player.answer("itm.phy.o.motion.0002", [{ part_id: "a", kind: "numeric", value: "20", unit: "m" }], 5000);
    const off = await player.answer("itm.phy.o.motion.0003", [{ part_id: "a", kind: "numeric", value: "30", unit: "s" }], 5000);
    expect(right?.verdict).toBe("correct");
    expect(off?.parts[0]).toMatchObject({ verdict: "incorrect", category: "unit_error" });
    expect(player.getView().checks["itm.phy.o.motion.0003"]?.status).toBe("marked");
    const sent = core.log.find((l) => l.method === "POST" && l.path.endsWith("/checks"))!;
    expect(sent.body).toMatchObject({ item_id: "itm.phy.o.motion.0002", time_ms: 5000, answer: { parts: [{ part_id: "a", kind: "numeric" }] } });
    expect(sent.headers["idempotency-key"]).toMatch(/^cli_/);
  });

  test("a slower ordinary load cannot replace the requested teaching entry for the same lesson", async () => {
    const core = new FakeProfileCore();
    core.lessons.set(LESSON.lesson_id, LESSON);
    const fetch = core.fetch;
    let release!: () => void, entered!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const started = new Promise<void>((resolve) => { entered = resolve; });
    let first = true;
    core.fetch = async (input, init) => {
      const response = await fetch(input, init);
      if (String(input).includes(`/v1/lessons/${LESSON.lesson_id}`)) {
        if (first) { first = false; entered(); await held; }
        else return Response.json({ ...await response.json(), title: "Teaching entry" });
      }
      return response;
    };
    const { profiles } = await unlocked(core);
    const player = new LessonController(profiles);
    const ordinary = player.load(LESSON.lesson_id);
    await started;
    await player.load(LESSON.lesson_id, true);
    release();
    await ordinary;
    expect(player.getView().lesson?.title).toBe("Teaching entry");
  });

  test("returning from tutor help retains the teaching position, scoped to the profile and lesson version", async () => {
    const { core, profiles } = await unlocked();
    core.lessons.set(LESSON.lesson_id, LESSON);
    const player = new LessonController(profiles);
    await player.load(LESSON.lesson_id, true);
    player.goTeaching(1);
    await player.load(LESSON.lesson_id, true);
    expect(player.getView().teachingIndex).toBe(1);
    core.lessons.set(LESSON.lesson_id, { ...LESSON, version: "0.2.0" });
    await player.load(LESSON.lesson_id, true);
    expect(player.getView().teachingIndex).toBe(0);
    player.goTeaching(1);
    await profiles.lock();
    await profiles.unlock(BEN.profile_id);
    await player.load(LESSON.lesson_id, true);
    expect(player.getView().teachingIndex).toBe(0);
  });

  test("step_lessons_send_the_try_and_read_the_explanation", async () => {
    const { core, profiles } = await unlocked();
    const steps = {
      ...LESSON, lesson_id: "les.phy.o.mechanics.motion_steps", position: null,
      blocks: [
        { type: "step", action: "try_first", text: "Try it.", visual: null, items: [item(1)] },
        { type: "step", action: "calculate", text: null, visual: null, items: [item(2)] },
        { type: "step", action: "calculate", text: null, visual: null, items: [item(3)] },
        { type: "check", items: [item(4), item(5), item(6)] },
      ],
    };
    expect(lessonProblems(steps)).toEqual([]);
    expect(lessonProblems({ ...steps, blocks: [{ type: "step", action: "guess", text: null, visual: null, items: [item(1)] }] })).toEqual(["blocks.0"]);
    expect(lessonProblems({ ...steps, blocks: [{ type: "step", action: "choose", text: null, visual: null, items: [item(1), item(2)] }] })).toEqual(["blocks.0"]);
    core.lessons.set(steps.lesson_id, steps);
    core.lessons.set(LESSON.lesson_id, LESSON);
    core.mark = () => ({ verdict: "incorrect", category: "value" });
    const player = new LessonController(profiles);
    await player.load(steps.lesson_id);
    const first = await player.answer("itm.phy.o.motion.0001", [{ part_id: "a", kind: "numeric", value: "1", unit: null }], 100);
    expect(first?.explanation).toBeNull();
    const second = await player.answer("itm.phy.o.motion.0001", [{ part_id: "a", kind: "numeric", value: "2", unit: null }], 100);
    expect(second?.explanation).toMatchObject({ shown: true, why: "A synthetic why for this step." });
    expect(player.getView().checks["itm.phy.o.motion.0001"]).toMatchObject({ tries: 2, answers: [{ value: "2" }] });
    const sent = core.log.filter((l) => l.path.endsWith("/checks")).map((l) => (l.body as { attempt?: number }).attempt);
    expect(sent).toEqual([1, 2]);
    // A script-shape lesson's checks send no try: an older core refuses the field it does not know.
    await player.load(LESSON.lesson_id);
    await player.answer("itm.phy.o.motion.0002", [{ part_id: "a", kind: "numeric", value: "20", unit: "m" }], 100);
    expect(core.log.filter((l) => l.path.endsWith("/checks")).at(-1)?.body).not.toHaveProperty("attempt");
    expect(checkResultProblems({ client_attempt_id: "cli_1", item_id: "x", verdict: "correct", marks_awarded: 1, marks_total: 1,
      parts: [{ part_id: "a", verdict: "correct", marks_awarded: 1, marks_total: 1, category: null, misconception: null, feedback: null, check_ids: [] }],
      explanation: { shown: false, why: 3, names: null, working: [] } })).toEqual(["explanation"]);
  });

  test("test_sec19_lock_drops_map_and_lesson", async () => {
    const { core, profiles } = await unlocked();
    core.maps.set(SUBJECT, map(["mastered"]));
    core.lessons.set(LESSON.lesson_id, LESSON);
    const controller = new SubjectMapController(profiles);
    const player = new LessonController(profiles);
    await controller.load(SUBJECT);
    await player.load(LESSON.lesson_id);
    const release = core.hold(`/v1/curriculum/${SUBJECT}/map`);
    const late = controller.load(SUBJECT);
    await profiles.lock();
    release();
    await late;
    expect(controller.getView()).toEqual({ status: "idle", subjectId: null, map: null });
    expect(player.getView().lesson).toBeNull();
    // With no profile unlocked the core refuses the reads.
    await controller.load(SUBJECT);
    expect(controller.getView().status).toBe("failed");
  });
});
