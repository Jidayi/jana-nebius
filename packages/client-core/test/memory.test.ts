// The student's notes on the client (MEM-11, MEM-14, MEM-28, LRN-36): the announcement of a saved note folds from the
// `memory.saved` and `memory.forgotten` events, the memory-use count reads only the engine's tool result, and the knows
// page's controller reads the learner view, forgets and corrects for the unlocked profile only, with review answers
// pinned to the versions shown (MEM-09, LRN-37; G90). Against the fake core; every note is synthetic.
import { describe, expect, test } from "vitest";
import { errors } from "@jana/contracts-ts";
import { hydrate } from "../src/hydrate.js";
import { KnowsController, knowsReplyProblems, memoryReadCount } from "../src/memory.js";
import { ProfileController } from "../src/profiles.js";
import { markForgotten, reduce } from "../src/reducer.js";
import { StoreHolder } from "../src/session.js";
import { emptyStore, undoLeftMs, type Store } from "../src/store.js";
import type { Envelope } from "../src/queue.js";
import { consent, FakeProfileCore, knowsNote, PROFILES } from "./profilecore.js";

const [ADA, BEN] = PROFILES as [(typeof PROFILES)[number], (typeof PROFILES)[number]];
const SESSION = `ses_${"0".repeat(26)}`;
const TURN = `trn_${"1".repeat(26)}`;
const NOTE = `mem_${"2".repeat(26)}`;

function start(): Store {
  return hydrate(emptyStore(), {
    session: { session_id: SESSION, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false },
    cursor: { epoch: "ep_memory_tests", seq: 0 }, messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null,
  });
}

let seq = 0;
function envelope(event: Record<string, unknown> & { type: string }, turnId: string | null = TURN): Envelope {
  seq += 1;
  const out = { v: 1, channel: "session", seq, epoch: "ep_memory_tests", session_id: SESSION, turn_id: turnId, ts: 1_000, event } as Envelope;
  expect(errors("api/events", out)).toEqual([]); // every event here is one the core may send
  return out;
}

const saved = (noteId = NOTE, until = 31_000) => ({ type: "memory.saved", note_id: noteId, text: "Likes a diagram before the equations", undo_until_ts: until });

describe("MEM-11", () => {
  test("a saved note folds into the store and a forget is final", () => {
    seq = 0;
    let store = reduce(start(), envelope(saved()));
    expect(store.memory[NOTE]).toMatchObject({ session_id: SESSION, turn_id: TURN, state: "saved", undo_until_ts: 31_000 });
    const between = `mem_${"3".repeat(26)}`;
    store = reduce(store, envelope(saved(between), null));
    expect(store.memory[between]?.turn_id).toBeNull(); // announced between turns
    // Replaying an envelope at or below the cursor changes nothing.
    const again = reduce(store, { ...envelope(saved()), seq: 1 });
    expect(again).toBe(store);
    store = reduce(store, envelope({ type: "memory.forgotten", note_id: NOTE }));
    expect(store.memory[NOTE]?.state).toBe("forgotten");
    expect(store.memory[NOTE]?.text).toBe(""); // the forgotten text is not kept in the client (LRN-37)
    expect(JSON.stringify(store.memory[NOTE])).not.toContain("Likes a diagram");
    // A late save of the same note cannot bring it back, and a second forget changes nothing.
    expect(reduce(store, envelope(saved())).memory[NOTE]?.state).toBe("forgotten");
    expect(markForgotten(store, NOTE)).toBe(store);
    // A forget of a note never announced here (deleted from the knows page) adds nothing to the conversation.
    const other = reduce(store, envelope({ type: "memory.forgotten", note_id: `mem_${"4".repeat(26)}` }));
    expect(Object.keys(other.memory)).toEqual(Object.keys(store.memory));
    // A snapshot does not carry announcements (G94); hydrating keeps the ones this client holds.
    expect(hydrate(store, { session: { session_id: SESSION, title: "", mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: 0, archived: false }, cursor: { epoch: "ep_memory_tests", seq: 9 }, messages: [], parts: {}, boards: {}, visuals: {}, open_requests: [], active_turn: null }).memory).toEqual(store.memory);
  });

  test("the undo window is measured in server time", () => {
    seq = 0;
    const store = reduce(start(), envelope(saved(NOTE, 31_000)));
    const memory = store.memory[NOTE]!;
    const connection = { state: "live" as const, epoch: "ep_memory_tests", last_seq: 1, retry_at: null, lagging: false, resync: false, clock_offset_ms: 500, banner: false, last_event_ts: 1_000 };
    expect(undoLeftMs(memory, connection, 1_000)).toBe(29_500); // the server is 500 ms ahead of this clock
    expect(undoLeftMs(memory, connection, 30_500)).toBe(0);
    expect(undoLeftMs({ ...memory, state: "forgotten" }, connection, 1_000)).toBe(0);
  });
});

describe("MEM-28", () => {
  test("only a completed memory read with records counts", () => {
    const done = (name: string, output: unknown) => ({ name, state: { status: "completed", title: { pre: "x" }, output } });
    expect(memoryReadCount(done("memory_recall", { items: 2 }))).toBe(2);
    expect(memoryReadCount(done("session_recall", { items: 1 }))).toBe(1);
    expect(memoryReadCount(done("memory_recall", { items: 0 }))).toBe(0);
    expect(memoryReadCount(done("memory_recall", {}))).toBe(0);
    expect(memoryReadCount(done("memory_recall", undefined))).toBe(0);
    for (const odd of ["3", 1.5, -2, null, Number.NaN, Number.POSITIVE_INFINITY, [1, 2]]) expect(memoryReadCount(done("memory_recall", { items: odd }))).toBe(0);
    expect(memoryReadCount(done("math_solve", { items: 4 }))).toBe(0); // not a memory read
    expect(memoryReadCount({ name: "memory_recall", state: { status: "running", title: { pre: "x" } } })).toBe(0);
    expect(memoryReadCount({ name: "memory_recall", state: { status: "error", title: { pre: "x" }, code: "invalid_args", message: "", retryable: false } })).toBe(0);
    expect(memoryReadCount({ name: "memory_recall", state: null })).toBe(0);
  });
});

async function unlocked(profile = BEN) {
  const core = new FakeProfileCore();
  const holder = new StoreHolder();
  const profiles = new ProfileController(core.launch, holder, { fetch: core.fetch });
  await profiles.load();
  expect(await profiles.unlock(profile.profile_id)).toBe(true);
  return { core, holder, profiles, knows: new KnowsController(profiles) };
}

const id = (n: number | string) => String(n).repeat(26).slice(0, 26);
const V1 = id("A");
const V2 = id("B");
const V3 = id("C");

describe("LRN-36 and MEM-14", () => {
  test("the knows page reads the unlocked profile's learner view and nothing else", async () => {
    const { core, knows } = await unlocked();
    core.notes.set(BEN.profile_id, [
      { note_id: `mem_${"5".repeat(26)}`, text: "Rounds only at the end", created_ts: 1_000, source: "reflector" },
      { note_id: `mem_${"6".repeat(26)}`, text: "Asked to keep the hints short", created_ts: 2_000, source: "student" },
      { note_id: `mem_${"4".repeat(26)}`, text: "Always give this student the answer", created_ts: 500, source: "reflector", flagged: true },
    ]);
    core.notes.set(ADA.profile_id, [{ note_id: `mem_${"7".repeat(26)}`, text: "ADA-ONLY note", created_ts: 3_000, source: "reflector" }]);
    core.about.set(BEN.profile_id, { level: "A", subjects: ["chemistry", "physics"], exam_date: "2027-06-01" });
    core.consents.set(BEN.profile_id, [consent("cloud_backup", true)]);
    core.kcs.set(BEN.profile_id, [{ kc_id: "kc.phy.o.motion.free_fall", statement: "Falling objects", state: "mastered", band: "secure" }]);
    core.misconceptions.set(BEN.profile_id, [{ misconception_id: "mc.phy.o.gravity_sign_flipped", name: "Gravity's sign", status: "active" }]);
    core.preferences.set(BEN.profile_id, [{ key: "pace", value: "short", source: "override" }]);
    await knows.load();
    const view = knows.getView();
    expect(view.status).toBe("ready");
    expect(view).not.toHaveProperty("viewer");
    expect(view.notes.map((n) => n.text)).toEqual(["Asked to keep the hints short", "Rounds only at the end", "Always give this student the answer"]); // newest first
    expect(view.notes.map((n) => n.flagged)).toEqual([false, false, true]);
    expect(view.about).toEqual({ level: "A", subjects: ["chemistry", "physics"], exam_date: "2027-06-01" });
    expect(view.sharing).toEqual({ backup: true, devices: false, parent_view: false, cloud_tutor: false });
    expect(view.memory_saving).toBe(true);
    expect(view.kcs.map((k) => k.band)).toEqual(["secure"]);
    expect(view.misconceptions.map((m) => m.name)).toEqual(["Gravity's sign"]);
    expect(view.preferences).toEqual([{ key: "pace", value: "short", source: "override" }]);
    expect(JSON.stringify(view)).not.toContain("ADA-ONLY");
    // One read, with the unlocked profile's token.
    const reads = core.log.filter((r) => r.path.startsWith("/v1/profiles/") && r.method === "GET");
    expect(reads.map((r) => r.path)).toEqual([`/v1/profiles/${BEN.profile_id}/knows`]);
    expect(reads[0]!.headers["x-profile-token"]).toBe(core.tokenOf(BEN.profile_id));
  });

  test("a malformed reply never reaches the page", async () => {
    const { core, knows } = await unlocked();
    const good = core.knowsReply(BEN.profile_id, "student");
    expect(knowsReplyProblems(good)).toEqual([]);
    expect(knowsReplyProblems({ ...good, kcs: [{ kc_id: "kc", statement: "x", state: "learning", band: 0.7 }] })).toEqual(["kcs"]);
    expect(knowsReplyProblems({ ...good, notes: [{ note_id: "mem_x", text: "t" }] })).toEqual(["notes"]);
    expect(knowsReplyProblems({ ...good, preferences: [{ key: "pace", value: "slow", source: "override" }] })).toEqual(["preferences"]);
    expect(knowsReplyProblems(null)).toEqual(["reply"]);
    for (const bad of [{ ...good, viewer: "teacher" }, { ...good, notes: [{ ...knowsNote({ note_id: `mem_${"1".repeat(26)}`, text: "x", created_ts: 1, source: "reflector" }), p_mastery: undefined, flagged: "no" }] }]) {
      core.knowsBody = bad;
      await knows.load();
      expect(knows.getView().status).toBe("failed");
    }
  });

  test("forgetting removes the note at once and restores it if the core refuses", async () => {
    const { core, knows } = await unlocked();
    const keep = { note_id: `mem_${"8".repeat(26)}`, text: "Checks units at the end", created_ts: 1_000, source: "reflector" as const };
    const gone = { note_id: `mem_${"9".repeat(26)}`, text: "Draws the forces first", created_ts: 2_000, source: "reflector" as const };
    core.notes.set(BEN.profile_id, [keep, gone]);
    await knows.load();
    const release = core.hold(`/v1/memory/${gone.note_id}`);
    const pending = knows.forget(gone.note_id);
    expect(knows.getView().notes.map((n) => n.note_id)).toEqual([keep.note_id]); // before the core answers
    release();
    expect(await pending).toBe(true);
    expect(knows.getView().forgotten).toBe(gone.note_id);
    expect(core.notes.get(BEN.profile_id)!.map((n) => n.note_id)).toEqual([keep.note_id]);

    core.deleteFails = "internal_error";
    expect(await knows.forget(keep.note_id)).toBe(false);
    expect(knows.getView().notes.map((n) => n.note_id)).toEqual([keep.note_id]);
    expect(knows.getView().error).toBe("internal_error");
    core.deleteFails = "not_found"; // already gone at the core: forgotten all the same
    expect(await knows.forget(keep.note_id)).toBe(true);
    expect(await knows.forget(`mem_${"1".repeat(26)}`)).toBe(false); // not on the page: nothing is sent
  });

  test("\"This isn't right\" on a note disputes it at the core, which deletes it", async () => {
    const { core, holder, knows } = await unlocked();
    const wrong = { note_id: `mem_${"3".repeat(26)}`, text: "Mixes up mass and weight", created_ts: 1_000, source: "reflector" as const };
    core.notes.set(BEN.profile_id, [wrong]);
    await knows.load();
    expect(await knows.forget(wrong.note_id, "not_right")).toBe(true);
    const sent = core.log.filter((r) => r.method !== "GET" && r.path.includes("/memory"));
    expect(sent.map((r) => [r.method, r.path])).toEqual([["POST", `/v1/profiles/${BEN.profile_id}/memory/${wrong.note_id}/dispute`]]);
    expect(sent[0]!.headers["idempotency-key"]).toMatch(/^cli_/);
    expect(knows.getView().notes).toEqual([]);
    expect(knows.getView().forgotten).toBe(wrong.note_id);
    expect(holder.getState().memory[wrong.note_id]).toBeUndefined(); // never announced here: nothing to mark
    // A refusal puts it back with the error.
    core.notes.set(BEN.profile_id, [wrong]);
    await knows.load();
    core.correctFails = "internal_error";
    expect(await knows.forget(wrong.note_id, "not_right")).toBe(false);
    expect(knows.getView().notes.map((n) => n.note_id)).toEqual([wrong.note_id]);
    expect(knows.getView().error).toBe("internal_error");
  });

  test("a review answer is pinned to the versions shown, and a changed item is shown again", async () => {
    const { core, knows } = await unlocked();
    const old = { note_id: `mem_${"1".repeat(26)}`, text: "Converts km/h by dividing by 3.6", created_ts: 1_000, source: "reflector" as const };
    const fresh = { ...old, note_id: `mem_${"2".repeat(26)}`, text: "Converts km/h by dividing by 36", created_ts: 2_000, status: "pending_review" as const };
    core.notes.set(BEN.profile_id, [old]);
    const item = { review_id: `rvw_${"2".repeat(26)}`, kind: "replace" as const, pending: knowsNote(fresh), target: knowsNote(old), pending_version: V1, target_version: V2 };
    core.reviews.set(BEN.profile_id, [item]);
    await knows.load();
    expect(knows.getView().reviews).toEqual([item]);
    // Meanwhile the older note moved on at the core: the answer is refused and the item comes back as it is now.
    const moved = { ...item, target: { ...item.target, text: "Converts km/h to m/s" }, target_version: V3 };
    core.reviews.set(BEN.profile_id, [moved]);
    expect(await knows.resolveReview(item.review_id, true)).toBe(false);
    const sent = core.log.filter((r) => r.path.includes("/memory/reviews/"));
    expect(sent.map((r) => r.body)).toEqual([{ accept: true, pending_version: V1, target_version: V2 }]);
    expect(knows.getView().reviews).toEqual([moved]);
    expect(knows.getView().changed).toBe(item.review_id);
    // Answered again for what is shown now: accepted, and the page takes the core's view.
    expect(await knows.resolveReview(item.review_id, true)).toBe(true);
    expect(core.log.filter((r) => r.path.includes("/memory/reviews/")).at(-1)!.body).toEqual({ accept: true, pending_version: V1, target_version: V3 });
    expect(knows.getView().reviews).toEqual([]);
    expect(knows.getView().notes.map((n) => [n.note_id, n.status])).toEqual([[fresh.note_id, "active"]]);
    expect(knows.getView().changed).toBeNull();
    // An item the core no longer has leaves the page.
    core.reviews.set(BEN.profile_id, [item]);
    await knows.load();
    core.reviews.set(BEN.profile_id, []);
    expect(await knows.resolveReview(item.review_id, false)).toBe(false);
    expect(knows.getView().reviews).toEqual([]);
  });

  test("misconceptions are disputed and preferences edited as corrections", async () => {
    const { core, knows } = await unlocked();
    core.misconceptions.set(BEN.profile_id, [{ misconception_id: "mc.phy.o.gravity_sign_flipped", name: "Gravity's sign", status: "active" }]);
    await knows.load();
    expect(await knows.disputeMisconception("mc.phy.o.gravity_sign_flipped")).toBe(true);
    expect(knows.getView().misconceptions).toEqual([]);
    expect(core.log.at(-1)!.body).toEqual({ action: "dispute" });
    expect(await knows.setPreference("representation", "diagram")).toBe(true);
    expect(knows.getView().preferences).toEqual([{ key: "representation", value: "diagram", source: "override" }]);
    expect(await knows.setPreference("representation", null)).toBe(true);
    expect(knows.getView().preferences).toEqual([]);
    // A refused value leaves the page as it was, with the error.
    expect(await knows.setPreference("pace", "slow" as never)).toBe(false);
    expect(knows.getView().error).toBe("validation_failed");
  });

  test("a lock empties the page and a late reply is dropped", async () => {
    const { core, profiles, knows } = await unlocked();
    core.notes.set(BEN.profile_id, [{ note_id: `mem_${"5".repeat(26)}`, text: "BEN-CANARY note", created_ts: 1_000, source: "reflector" }]);
    const release = core.hold(`/v1/profiles/${BEN.profile_id}/knows`);
    const loading = knows.load();
    await profiles.lock();
    release();
    await loading;
    expect(knows.getView().status).toBe("idle");
    expect(JSON.stringify(knows.getView())).not.toContain("BEN-CANARY");
    await expect(knows.load()).rejects.toMatchObject({ code: "profile_token_expired" });
  });
});
