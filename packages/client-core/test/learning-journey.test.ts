import { expect, test } from "vitest";
import { LearningJourneyController, ProfileController, StoreHolder, type LearningJourneyView } from "../src/index.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const journey: LearningJourneyView = {
  goal: { node_id: "cur.phy.o.forces", kc_id: "kc.phy.o.forces.force", title: "Forces", objective: "Calculate a force", subject: "physics" },
  source: null, source_changed: false, phase: "ready", evidence: "none", prior_attempts: 0,
  practice_set_id: null, lesson_id: null, lesson_opened: false, stage: "starting",
};

test("journey replies are validated and profile clearing drops both current and delayed results", async () => {
  const core = new FakeProfileCore();
  let reply: unknown = { journey }, finish: ((value: Response) => void) | null = null, delayed = false;
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: async (input, init) => {
    if (String(input).includes("/v1/learning-journey")) {
      if (delayed) return new Promise<Response>((resolve) => { finish = resolve; });
      return new Response(JSON.stringify(reply), { status: 200 });
    }
    return core.fetch(input, init);
  } });
  await profiles.load(); await profiles.unlock(PROFILES[1]!.profile_id);
  const controller = new LearningJourneyController(profiles);
  expect(await controller.start(journey.goal.node_id, journey.goal.kc_id)).toEqual(journey);
  reply = { journey: { ...journey, phase: "mastered" } };
  expect(await controller.load()).toBeNull(); expect(controller.getView().error).toBe(true);
  delayed = true; const pending = controller.load();
  await Promise.resolve(); await Promise.resolve();
  await profiles.unlock(PROFILES[0]!.profile_id);
  finish?.(new Response(JSON.stringify({ journey }), { status: 200 }));
  await pending;
  expect(controller.getView().journey).toBeNull();
});

test("a background refresh cannot discard a mutation, and duplicate actions do not create a second set", async () => {
  const core = new FakeProfileCore();
  let release: ((response: Response) => void) | undefined;
  let posts = 0;
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: async (input, init) => {
    if (String(input).includes("/v1/learning-journey")) {
      if (init?.method === "POST") { posts++; return new Promise<Response>((resolve) => { release = resolve; }); }
      return new Response(JSON.stringify({ journey: null }));
    }
    return core.fetch(input, init);
  } });
  await profiles.load(); await profiles.unlock(PROFILES[1]!.profile_id);
  const controller = new LearningJourneyController(profiles);
  const starting = controller.start(journey.goal.node_id, journey.goal.kc_id, "les.phy.o.forces");
  await Promise.resolve(); await Promise.resolve();
  await controller.load();
  expect(await controller.step("practice")).toBeNull();
  release!(new Response(JSON.stringify({ journey })));
  expect(await starting).toEqual(journey);
  expect(controller.getView()).toMatchObject({ journey, busy: false, error: false });
  expect(posts).toBe(1);
});
