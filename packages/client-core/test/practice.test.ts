// UXS-24 and API-27 against the core that serves practice sets (M16): its replies carry what the proposed contract
// additions describe (a reflection card on a mark, a "not_checked" verdict, a set with no question to show) and the
// client takes them, while anything else malformed is still refused at the boundary; an older core without the route
// leaves the view "unavailable". Over the fake core, with synthetic items.
import { describe, expect, test } from "vitest";
import { PracticeController, ProfileController, StoreHolder, settled } from "../src/index.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const ITEM = {
  item_id: "itm.phy.o.synthetic.0001", pack_id: "pack.phy.o", pack_version: "1.0.0", kc_ids: ["kc.phy.o.synthetic"], kind: "numeric",
  stem: "A synthetic question.", parts: [{ part_id: "a", prompt: "A synthetic question.", uses_parts: [], input: { kind: "numeric", unit_prompt: null }, marks: 1 }],
  visual: null, marks: 1,
};

async function started(core = new FakeProfileCore()) {
  core.practiceItems = [ITEM, { ...ITEM, item_id: "itm.phy.o.synthetic.0002" }];
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: (input, init) => core.fetch(input, init) });
  await profiles.load();
  expect(await profiles.unlock(PROFILES[1]!.profile_id)).toBe(true);
  const practice = new PracticeController(profiles);
  await practice.start("physics");
  return { core, practice };
}

const answer = [{ part_id: "a", kind: "numeric" as const, value: "2", unit: "m/s^2" }];

describe("UXS-24", () => {
  test("a lost response recovers the committed mark using the same request, despite later edits", async () => {
    const { core, practice } = await started();
    const original = core.fetch;
    let cached: string | null = null;
    let recover = false;
    const requests: { body: unknown; key: string | undefined }[] = [];
    core.fetch = async (input, init) => {
      if (init?.method !== "POST" || !String(input).endsWith("/answers")) return original(input, init);
      requests.push({ body: JSON.parse(String(init.body)), key: (init.headers as Record<string, string>)["idempotency-key"] });
      cached ??= await (await original(input, init)).text();
      if (!recover) throw new TypeError("response lost after commit");
      return new Response(cached, { status: 200 });
    };
    expect(await practice.answer(answer, 1000)).toBeNull();
    expect(practice.getView().markFailed).toBe(true);
    recover = true;
    expect(await practice.answer([{ ...answer[0]!, value: "999" }], 2000)).not.toBeNull();
    expect(requests).toHaveLength(3);
    expect(requests[1]).toEqual(requests[0]); expect(requests[2]).toEqual(requests[0]);
    expect(practice.getView()).toMatchObject({ closed: true, markFailed: false, tries: [{ answers: answer }] });
    practice.advance();
    await practice.answer(answer, 1000);
    expect(requests[3]?.key).not.toBe(requests[0]?.key);
  });
  test("test_uxs24_practice_sets_from_the_core", async () => {
    const { core, practice } = await started();
    expect(practice.getView()).toMatchObject({ status: "ready", number: 1, total: 2, item: { item_id: ITEM.item_id } });
    // A mark with its reflection card (M16) is taken, and the answer went to the set's own route.
    const marked = await practice.answer(answer, 1200);
    expect(marked?.verdict).toBe("correct");
    expect(marked?.reflection).toMatchObject({ card_type: "reflection" });
    expect(core.log.some((r) => /^\/v1\/practice\/sets\/set_[^/]+\/answers$/.test(r.path))).toBe(true);
    expect(practice.getView().tries).toHaveLength(1);
  });

  test("test_asm28_a_first_miss_keeps_the_question_then_the_worked_answer", async () => {
    // Help before the answer (ASM-28): a first miss keeps the question open with no answer; the second miss carries the
    // worked answer (checked as the adopted worked example) and closes it; "Next question" shows the one the core gave.
    const { core, practice } = await started();
    core.mark = () => ({ verdict: "incorrect", category: "units" });
    expect((await practice.answer(answer, 800))?.verdict).toBe("incorrect");
    expect(practice.getView()).toMatchObject({ closed: false, next: null, worked: null });
    const second = await practice.answer([{ ...answer[0]!, value: "3" }], 800);
    expect(second?.worked?.final_answer.check_id).toBe("chk_fake_key");
    expect(practice.getView()).toMatchObject({ closed: true, next: { item_id: "itm.phy.o.synthetic.0002" }, worked: { worked_example_id: "we.fake" } });
    const sent = core.log.filter((r) => r.path.endsWith("/answers")).length;
    expect(await practice.answer(answer, 800)).toBeNull(); // closed: nothing more is sent
    expect(core.log.filter((r) => r.path.endsWith("/answers"))).toHaveLength(sent);
    practice.advance();
    expect(practice.getView()).toMatchObject({ number: 2, closed: false, tries: [], worked: null, item: { item_id: "itm.phy.o.synthetic.0002" } });
  });

  test("test_asm28_dont_know_shows_the_worked_answer_and_moves_on", async () => {
    const { core, practice } = await started();
    expect(await practice.reveal()).toBe(true);
    expect(core.log.find((r) => r.path.endsWith("/reveal"))?.body).toEqual({ item_id: ITEM.item_id });
    expect(practice.getView()).toMatchObject({ closed: true, revealing: false, worked: { worked_example_id: "we.fake" }, next: { item_id: "itm.phy.o.synthetic.0002" } });
    expect(await practice.reveal()).toBe(false); // closed: asked once
    // A malformed worked answer is refused at the boundary and the question stays as it was.
    practice.advance();
    const original = core.fetch;
    core.fetch = async (input, init) => {
      const response = await original(input, init);
      if (!String(input).endsWith("/reveal")) return response;
      const body = await response.json() as Record<string, unknown>;
      body.worked = { steps: [] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    };
    expect(await practice.reveal()).toBe(false);
    expect(practice.getView()).toMatchObject({ closed: false, worked: null, revealing: false });
  });

  test("an answer the marker does not check settles the question", async () => {
    const { core, practice } = await started();
    core.mark = () => ({ verdict: "not_checked", category: null });
    const marked = await practice.answer(answer, 500);
    expect(marked?.verdict).toBe("not_checked");
    expect(settled(marked!)).toBe(true);
  });

  test("a malformed reflection card or a malformed mark is still refused", async () => {
    const core = new FakeProfileCore();
    const { practice } = await started(core);
    const original = core.fetch;
    let broken: "reflection" | "verdict" = "reflection";
    core.fetch = async (input, init) => {
      const response = await original(input, init);
      if (!String(input).includes("/answers")) return response;
      const body = await response.json() as Record<string, unknown>;
      if (broken === "reflection") body.reflection = { card_type: "reflection" };
      else body.verdict = "almost";
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    };
    expect(await practice.answer(answer, 500)).toBeNull();
    expect(practice.getView().markFailed).toBe(true);
    broken = "verdict";
    expect(await practice.answer(answer, 500)).toBeNull();
    expect(practice.getView().markFailed).toBe(true);
  });

  test("a set with no question to show is finished, and an older core without the route is unavailable", async () => {
    const empty = new FakeProfileCore();
    const { practice } = await started(empty);
    empty.practiceItems = [];
    await practice.start("physics");
    expect(practice.getView().status).toBe("done");
    const old = new FakeProfileCore();
    old.practiceServed = false;
    const { practice: older } = await started(old);
    expect(older.getView().status).toBe("unavailable");
  });
});
