import { expect, test } from "vitest";
import { SavedQuestionsController } from "../src/saved-questions.js";
import { ProfileController } from "../src/profiles.js";
import { StoreHolder } from "../src/session.js";
import { PROFILES } from "./profilecore.js";
import { SAVED, savedCore } from "./savedcore.js";
async function setup() {
  const fake = savedCore(), profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load(); await profiles.unlock(PROFILES[0]!.profile_id);
  return { ...fake, profiles, saved: new SavedQuestionsController(profiles) };
}
test("uxs42_saved_questions_local", async () => {
  const s = await setup();
  await s.saved.save(SAVED.session_id, "trn_00000000000000000000000001");
  const restarted = new SavedQuestionsController(s.profiles); await restarted.load();
  restarted.select(SAVED.question_id); expect(restarted.getView().questions).toEqual([SAVED]);
  await restarted.status(SAVED.question_id, "sorted"); expect(restarted.getView().questions[0]?.status).toBe("sorted");
  await restarted.remove(SAVED.question_id); expect(restarted.getView().questions).toEqual([]);
  expect(s.requests.map((r) => r.method)).toEqual(["POST", "PATCH", "DELETE"]);
  expect(s.requests.every((r) => r.path.startsWith("/v1/saved-questions") && r.key?.startsWith("cli_"))).toBe(true);
});
test("lost mutation response retains its request and a retry never saves twice", async () => {
  const s = await setup(); s.lose(true);
  expect(await s.saved.save(SAVED.session_id, "trn_00000000000000000000000001")).toBe(false);
  expect(s.saved.getView().uncertain).toBe(true); s.lose(false);
  expect(await s.saved.retry()).toBe(true);
  expect(s.requests).toHaveLength(3); expect(s.requests[2]).toEqual(s.requests[0]);
  expect(s.saved.getView().questions).toHaveLength(1);
});
test("another student cannot inherit the list, selection, or late save response", async () => {
  const s = await setup(); const late = s.saved.save(SAVED.session_id, "trn_00000000000000000000000001");
  await s.profiles.unlock(PROFILES[1]!.profile_id); await late; await s.saved.load();
  expect(s.saved.getView()).toMatchObject({ questions: [], selected: null, saved: null });
});
