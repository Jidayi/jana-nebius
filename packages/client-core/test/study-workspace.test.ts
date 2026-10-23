import { expect, test, vi } from "vitest";
import { StudyWorkspaceController, EMPTY_STUDY } from "../src/study-workspace.js";
import { CommandClient } from "../src/stream/commands.js";
import type { ProfileController } from "../src/profiles.js";
import type { LocalSpeech } from "../src/speech.js";
const sid = `src_${"0".repeat(26)}`, now = "2026-10-18T00:00:00Z";
const SOURCE = { source_id: sid, revision: 1, kind: "text", title: "Biology", state: "ready", private: false, created_at: now, updated_at: now, readable_units: 1, unreadable_units: [], sha256: "0".repeat(64) };
function setup(get: (path: string) => Promise<unknown>, post = vi.fn(async () => SOURCE), speech?: LocalSpeech) {
  let clear = () => {};
  const wrappedPost = vi.fn(async (path: string, ...args: unknown[]) => path.startsWith("/v1/study/retries/") ? { client_key: `cli_${"0".repeat(26)}`, expires_at: "2099-10-18T00:05:00Z" } : (post as unknown as (path: string, ...args: unknown[]) => Promise<unknown>)(path, ...args));
  const commands = { get: vi.fn(get), post: wrappedPost, request: vi.fn(async (method: string, path: string, body: unknown, key: string, headers: unknown) => (post as unknown as (path: string, ...args: unknown[]) => Promise<unknown>)(path, body, key, headers)), delete: vi.fn(async () => undefined), scoped: vi.fn() };
  commands.scoped.mockImplementation(() => commands);
  const profiles = { generation: 1, commands, onClear: (fn: () => void) => { clear = fn; }, getView: () => ({ settings: null }) };
  const controller = new StudyWorkspaceController(profiles as unknown as ProfileController, speech);
  return { controller, profiles, clear: () => { profiles.generation++; clear(); } };
}
test("workspace rejects malformed wire data and clears late profile responses", async () => {
  const invalid = setup(async () => ({ sources: { items: [{ source_id: "bad" }], next_cursor: null }, jobs: [] }));
  await invalid.controller.load(); expect(invalid.controller.getView().status).toBe("failed");
  let release!: (value: unknown) => void;
  const late = setup(() => new Promise((resolve) => { release = resolve; }));
  const pending = late.controller.load(); late.clear(); release({ sources: { items: [SOURCE], next_cursor: null }, jobs: [] }); await pending;
  expect(late.controller.getView()).toEqual(EMPTY_STUDY);
});
test("opening uses an explicit short-lived grant and close removes source prose", async () => {
  const post = vi.fn(async () => ({ source: { ...SOURCE, private: true }, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" }));
  const fake = setup(async () => ({ items: [], next_cursor: null }), post as never);
  await fake.controller.open(sid);
  expect(fake.controller.getView().source?.title).toBe("Biology");
  expect(post).toHaveBeenCalledWith(`/v1/study/sources/${sid}/open`, { confirm: true }, expect.stringMatching(/^cli_/));
  expect(fake.profiles.commands.get).toHaveBeenCalledWith(expect.stringContaining("/content"), { "X-Study-Open": "t".repeat(43) });
  fake.controller.close();
  expect(fake.profiles.commands.delete).toHaveBeenCalledWith(`/v1/study/sources/${sid}/open`, expect.stringMatching(/^cli_/), { "X-Study-Open": "t".repeat(43) });
  expect(fake.controller.getView().source).toBeNull(); expect(fake.controller.getView().chunks).toEqual([]);
});
test("a late open cannot repopulate a closed reader", async () => {
  let release!: (value: unknown) => void;
  const post = vi.fn(() => new Promise((resolve) => { release = resolve; }));
  const fake = setup(async () => ({ items: [], next_cursor: null }), post as never);
  const pending = fake.controller.open(sid); fake.controller.close();
  release({ source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" }); await pending;
  expect(fake.controller.getView().source).toBeNull(); expect(fake.profiles.commands.get).not.toHaveBeenCalled();
});


test("material request retries cannot rebind to another profile", async () => {
  let current = true;
  const fetch = vi.fn(async () => { current = false; throw new Error("connection lost during profile switch"); });
  const endpoint = vi.fn(async () => ({ baseUrl: "http://core.test", token: "launch", headers: { "x-profile-token": "original-profile" } }));
  const commands = new CommandClient({ endpoint, fetch: fetch as never }).scoped(() => current);
  await expect(commands.post("/v1/study/sources", { kind: "text", text: "private source" }, "cli_example")).rejects.toMatchObject({ code: "profile_token_expired" });
  expect(fetch).toHaveBeenCalledTimes(1); expect(endpoint).toHaveBeenCalledTimes(1);
});

test("closing during overview playback cancels speech and drops late completion", async () => {
  const aidId = `aid_${"0".repeat(26)}`;
  const aid = { aid_id: aidId, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", title: "Overview", sources: [{ source_id: sid, revision: 1 }], claims: [{ text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] }], status: "ready", created_at: now };
  const cancel = vi.fn(); let end: (() => void) | undefined;
  const speech: LocalSpeech = { available: () => true, subscribe: () => () => {}, speak: vi.fn((_text, callbacks) => { end = callbacks.end; return cancel; }) };
  const fake = setup(async (path) => path.includes("/speech") ? { aid_id: aidId, claim_index: 0, text: "DNA", next_offset: null, last_claim: true } : aid, undefined, speech);
  await fake.controller.showAid(aidId);
  const pending = fake.controller.playOverview();
  await vi.waitFor(() => expect(speech.speak).toHaveBeenCalledWith("DNA", expect.any(Object)));
  fake.clear(); end?.(); await pending;
  expect(cancel).toHaveBeenCalledTimes(1);
  expect(fake.controller.getView().reading).toBe(false);
  expect(fake.controller.getView().aid).toBeNull();
});

test("a replacement controller recovers the pending mutation key until acknowledgement", async () => {
  let key: string | null = null, first = true;
  const keys: string[] = [];
  const commands = {
    scoped: () => commands,
    post: vi.fn(async (path: string) => {
      if (path.includes("/retries/")) { key ??= `cli_${"1".repeat(26)}`; return { client_key: key, expires_at: "2099-10-18T00:05:00Z" }; }
      return { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" };
    }),
    request: vi.fn(async (_method: string, _path: string, _body: unknown, id: string) => {
      keys.push(id);
      if (first) { first = false; throw new Error("lost response"); }
      return SOURCE;
    }),
    delete: vi.fn(async (path: string) => { if (path.includes("/retries/")) key = null; }),
    get: vi.fn(async (path: string) => path === "/v1/study/workspace" ? { sources: { items: [SOURCE], next_cursor: null }, jobs: [] } : { items: [], next_cursor: null }),
  };
  const profiles = { generation: 1, commands, onClear: () => {} } as unknown as ProfileController;
  await new StudyWorkspaceController(profiles).addText("Biology", "DNA stores genetic information.");
  expect(key).not.toBeNull();
  await new StudyWorkspaceController(profiles).addText("Biology", "DNA stores genetic information.");
  expect(keys).toHaveLength(2); expect(keys[0]).toBe(keys[1]); expect(key).toBeNull();
});

test("refresh removes an aid deleted through another source instead of keeping cached prose", async () => {
  const id = `aid_${"0".repeat(26)}`;
  const aid = { aid_id: id, job_id: `stj_${"0".repeat(26)}`, kind: "notes", title: "Notes", sources: [{ source_id: sid, revision: 1 }], claims: [{ text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] }], status: "ready", created_at: now };
  let removed = false;
  const fake = setup(async (path) => {
    if (path === "/v1/study/workspace") return { sources: { items: [SOURCE], next_cursor: null }, jobs: [] };
    if (path === `/v1/study/sources/${sid}`) return SOURCE;
    if (path === `/v1/study/aids/${id}`) return aid;
    return { items: path.startsWith("/v1/study/aids?") && !removed ? [aid] : [], next_cursor: null };
  }, vi.fn(async () => ({ source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" })) as never);
  await fake.controller.open(sid); await fake.controller.showAid(id);
  expect(fake.controller.getView().aid?.claims[0]?.text).toBe("DNA");
  removed = true; await fake.controller.refreshOpened();
  expect(fake.controller.getView().aid).toBeNull();
  expect(fake.controller.getView().aids).toEqual([]);
});

test("Study safety template survives the error boundary and clears on profile switch", async () => {
  const { CommandError } = await import("../src/stream/commands.js");
  const post = vi.fn(async () => { throw new CommandError(422, "validation_failed", false, { reason: "safety_template", template_id: "tpl.distress", calm_screen: true }); });
  const fake = setup(async () => ({}), post as never);
  await fake.controller.addText("Biology", "Synthetic source");
  expect(fake.controller.getView()).toMatchObject({ error: "safety_template", safetyTemplate: "tpl.distress" });
  fake.clear();
  expect(fake.controller.getView().safetyTemplate).toBeUndefined();
});

const AID = `aid_${"0".repeat(26)}`, QUIZ = `sqz_${"0".repeat(26)}`, CHUNK = `sck_${"0".repeat(26)}`;
const cite = (text: string) => ({ text, citations: [{ source_id: sid, revision: 1, chunk_id: CHUNK, start: 0, end: 3, quote: "DNA" }] });
const GRANT = { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" };

test("stu21_settings_respected: the Generate settings travel with the job", async () => {
  const post = vi.fn(async (path: string) => path.endsWith("/open") ? GRANT : { job_id: `stj_${"0".repeat(26)}`, kind: "quiz", sources: [{ source_id: sid, revision: 1 }], state: "queued", completed_units: 0, total_units: null, result_ids: [], error: null, created_at: now, updated_at: now });
  const fake = setup(async () => ({ items: [], next_cursor: null }), post as never);
  await fake.controller.open(sid);
  const settings = { question_types: ["fill_blank", "true_false"] as ("fill_blank" | "true_false")[], difficulty: "hard" as const, topics: ["Enzymes"], focus: "temperature" };
  await fake.controller.generate("quiz", 12, false, false, undefined, settings);
  expect(post).toHaveBeenLastCalledWith("/v1/study/jobs", { kind: "quiz", execution: "local", sources: [{ source_id: sid, revision: 1 }], count: 12, settings }, expect.stringMatching(/^cli_/), expect.anything());
  await fake.controller.generate("lesson_plan", 10, false, false, undefined, { minutes_available: 30, ready_by: "2026-11-02" });
  expect(post).toHaveBeenLastCalledWith("/v1/study/jobs", { kind: "lesson_plan", execution: "local", sources: [{ source_id: sid, revision: 1 }], settings: { minutes_available: 30, ready_by: "2026-11-02" } }, expect.stringMatching(/^cli_/), expect.anything());
});

test("stu21_sets_persist_progress: My Sets loads with the library and a set opens where it was left", async () => {
  const set = { aid_id: AID, kind: "quiz", sources: [{ source_id: sid, revision: 1 }], status: "ready", created_at: now, private: false, title: "Biology", progress: { questions_total: 5, questions_left: 3 } };
  const draft = { quiz_revision: 1, answers: [{ item_id: "q1", answer: "true" }], position: 1 };
  const quiz = { quiz_id: QUIZ, aid_id: AID, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cite("DNA is a protein.") }, { item_id: "q2", type: "fill_blank", stem: cite("____ stores genes.") }], draft };
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "quiz", sources: [{ source_id: sid, revision: 1 }], title: "Biology", claims: [cite("DNA")], status: "ready", created_at: now, quiz_id: QUIZ };
  const fake = setup(async (path) => {
    if (path === "/v1/study/workspace") return { sources: { items: [SOURCE], next_cursor: null }, jobs: [] };
    if (path === "/v1/study/sets") return { items: [set], next_cursor: null };
    if (path === `/v1/study/aids/${AID}`) return aid;
    if (path === `/v1/study/quizzes/${QUIZ}`) return quiz;
    return { items: [], next_cursor: null };
  }, vi.fn(async (path: string, body: unknown) => path.endsWith("/open") ? GRANT : body) as never);
  await fake.controller.load();
  expect(fake.controller.getView().sets).toEqual([set]);
  await fake.controller.openSet(fake.controller.getView().sets[0]!);
  expect(fake.controller.getView().source?.source_id).toBe(sid);
  expect(fake.controller.getView().quiz?.draft).toEqual(draft);
  await fake.controller.saveDraft({ q1: "false", q2: "" }, 1);
  expect(fake.profiles.commands.request).toHaveBeenLastCalledWith("PUT", `/v1/study/quizzes/${QUIZ}/draft`, { quiz_revision: 1, position: 1, answers: [{ item_id: "q1", answer: "false" }] }, expect.stringMatching(/^cli_/), expect.anything());
  expect(fake.controller.getView().quiz?.draft?.answers).toEqual([{ item_id: "q1", answer: "false" }]);
});

test("stu22_chapters_and_seek: a citation to a recording moves the player to its moment", async () => {
  const recording = { ...SOURCE, kind: "recording", duration_ms: 120000 };
  const chunks = [0, 60000].map((start, i) => ({ chunk_id: `sck_${String(i).repeat(26)}`, source_id: sid, revision: 1, ordinal: i, locator: { kind: "time", start_ms: start, end_ms: start + 60000 }, text: i ? "Respiration releases energy." : "DNA stores genetic information.", sha256: "0".repeat(64) }));
  const fake = setup(async (path) => path.includes("/content") ? { items: chunks, next_cursor: null } : { items: [], next_cursor: null }, vi.fn(async () => ({ ...GRANT, source: recording })) as never);
  await fake.controller.open(sid);
  expect(fake.controller.getView().playhead).toBeNull();
  const ok = await fake.controller.readCitation({ source_id: sid, revision: 1, chunk_id: `sck_${"1".repeat(26)}`, start: 0, end: 11, quote: "Respiration" });
  expect(ok).toBe(true);
  expect(fake.controller.getView().playhead).toEqual({ ms: 60000, seq: 1 });
  fake.controller.seek(0);
  expect(fake.controller.getView().playhead).toEqual({ ms: 0, seq: 2 });
  fake.controller.close();
  expect(fake.controller.getView().playhead).toBeNull();
});

test("voc53_study_place_chat: the open source is the Chat tab's voice place and a spoken answer opens there", async () => {
  const aidId = `aid_${"1".repeat(26)}`;
  const aid = { aid_id: aidId, job_id: `stj_${"0".repeat(26)}`, kind: "chat", prompt: "What is DNA?", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [{ text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] }], status: "ready", created_at: now };
  const post = vi.fn(async () => ({ source: { ...SOURCE, private: true }, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" }));
  const fake = setup(async (path) => path.startsWith("/v1/study/aids?") ? { items: [aid], next_cursor: null } : path.startsWith("/v1/study/aids/") ? aid : { items: [], next_cursor: null }, post as never);
  expect(fake.controller.voicePlace()).toBeNull(); // nothing open: no conversation
  await fake.controller.open(sid);
  expect(fake.controller.voicePlace()).toEqual({ place: "study", source_id: sid, revision: 1, open: "t".repeat(43) });
  await fake.controller.voiced({ place: "ask", aid_id: aidId });
  expect(fake.controller.getView().aid).toBeNull(); // Ask anything's answers are not the Chat tab's
  await fake.controller.voiced({ place: "study", aid_id: aidId });
  expect(fake.controller.getView().aid?.aid_id).toBe(aidId);
  expect(fake.controller.getView().aids.map((a) => a.aid_id)).toContain(aidId);
  fake.controller.close();
  expect(fake.controller.voicePlace()).toBeNull();
});

test("test_stu20_chat_answer_opens: the answer to the question just asked opens when it is ready (D132)", async () => {
  const jobId = `stj_${"2".repeat(26)}`, aidId = `aid_${"2".repeat(26)}`;
  const job = { job_id: jobId, kind: "chat", sources: [{ source_id: sid, revision: 1 }], state: "queued", completed_units: 0, total_units: 1, result_ids: [], error: null, created_at: now, updated_at: now };
  const answer = { aid_id: aidId, job_id: jobId, kind: "chat", prompt: "What is DNA?", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [{ text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] }], status: "ready", created_at: now };
  let ready = false;
  const post = vi.fn(async (path: string) => path === "/v1/study/jobs" ? job : { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" });
  const fake = setup(async (path) => {
    if (path === "/v1/study/workspace") return { sources: { items: [SOURCE], next_cursor: null }, jobs: [] };
    if (path === `/v1/study/sources/${sid}`) return SOURCE;
    return { items: path.startsWith("/v1/study/aids?") && ready ? [answer] : [], next_cursor: null };
  }, post as never);
  await fake.controller.open(sid);
  await fake.controller.generate("chat", 10, false, false, "What is DNA?");
  await fake.controller.refreshOpened();
  expect(fake.controller.getView().aid).toBeNull(); // still working
  ready = true; await fake.controller.refreshOpened();
  expect(fake.controller.getView().aid?.aid_id).toBe(aidId);
});
