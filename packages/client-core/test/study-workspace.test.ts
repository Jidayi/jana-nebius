import { expect, test, vi } from "vitest";
import { StudyWorkspaceController, EMPTY_STUDY, type PodcastAudio } from "../src/study-workspace.js";
import { CommandClient } from "../src/stream/commands.js";
import { ProfileController } from "../src/profiles.js";
import { StoreHolder } from "../src/index.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";
import type { LocalSpeech } from "../src/speech.js";
const sid = `src_${"0".repeat(26)}`, now = "2026-10-18T00:00:00Z";
const SOURCE = { source_id: sid, revision: 1, kind: "text", title: "Biology", state: "ready", private: false, created_at: now, updated_at: now, readable_units: 1, unreadable_units: [], sha256: "0".repeat(64) };
test.each(["adult", "minor", "verified_minor", "device_off", "no_plan", "pending_subscription"])("Study access preflight: %s", async (scenario) => {
  const core = new FakeProfileCore(), id = PROFILES[1]!.profile_id;
  if (!["minor", "verified_minor"].includes(scenario)) core.adults.add(id);
  core.features.study_materials = scenario !== "device_off";
  core.features.cloud_tier = true;
  if (scenario !== "no_plan") core.subscription = { state: "active", subscription_id: "sub_test_1", period_end: "2026-12-31T00:00:00.000Z", allowance_used_up: false, profiles: [{ profile_id: id, consent: "recorded" }] };
  if (scenario === "pending_subscription") { core.subscription.state = "pending_consent"; core.subscription.profiles[0]!.consent = "needed"; }
  core.consents.set(id, (["cloud_tier", "study_materials"] as const).map((scope) => ({ scope, granted: true, effective: true, paused: false, granted_by_role: scenario === "verified_minor" ? "guardian" : "student_18_plus", method: scenario === "verified_minor" ? "checkout_guardian" : "in_app_notice", notice_version: "v1", granted_at: now })));
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
  await profiles.load(); await profiles.unlock(id);
  const study = new StudyWorkspaceController(profiles);
  await study.loadAccess();
  expect(study.getView().access).toEqual({ status: ["minor", "pending_subscription"].includes(scenario) ? "consent_required" : scenario === "device_off" ? "study_off" : scenario === "no_plan" ? "plan_required" : "ready", needsGuardian: scenario === "minor" });
  expect(core.consentSwitches).toEqual([]);
  expect(core.log.filter((r) => ["PUT", "PATCH"].includes(r.method) && /consents|connectivity/.test(r.path))).toEqual([]);
});
test("a file is saved locally while Study permission is pending, without starting cloud processing", async () => {
  const core = new FakeProfileCore(), id = PROFILES[1]!.profile_id;
  core.features.study_materials = true;
  core.subscription = { state: "active", subscription_id: "sub_test_1", period_end: "2026-12-31T00:00:00.000Z", allowance_used_up: false, profiles: [{ profile_id: id, consent: "recorded" }] };
  const queued = { ...SOURCE, kind: "pdf", title: "notes.pdf", state: "queued", readable_units: 0 };
  const processing = vi.fn();
  let uploaded = 0;
  const fetch: typeof globalThis.fetch = async (input, init) => {
    const path = new URL(String(input)).pathname, method = init?.method ?? "GET";
    if (!path.startsWith("/v1/study/")) return core.fetch(input, init);
    if (method === "DELETE") return new Response(null, { status: 204 });
    let body: unknown = { items: [], next_cursor: null };
    if (path.includes("/retries/")) body = { client_key: `cli_${"0".repeat(26)}`, expires_at: "2099-10-18T00:05:00Z" };
    else if (path === "/v1/study/sources" && method === "POST") body = { ...queued, state: "uploading" };
    else if (method === "PUT" && path.includes("/chunks/")) { uploaded++; body = { received_bytes: 13, complete: true }; }
    else if (path === "/v1/study/jobs") { processing(); throw new Error("must not process without consent"); }
    else if (path === "/v1/study/workspace") body = { sources: { items: [queued], next_cursor: null }, jobs: [] };
    else if (path.endsWith("/open")) body = { source: queued, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" };
    else if (path === `/v1/study/sources/${sid}`) body = queued;
    return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
  };
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch });
  await profiles.load(); await profiles.unlock(id);
  const study = new StudyWorkspaceController(profiles);
  await study.loadAccess();
  await study.upload(new File(["synthetic PDF"], "notes.pdf", { type: "application/pdf" }), undefined, true);
  expect(uploaded).toBe(1);
  expect(processing).not.toHaveBeenCalled();
  expect(study.getView()).toMatchObject({ error: null, source: { title: "notes.pdf", state: "queued" }, access: { status: "consent_required" } });
});
function setup(get: (path: string) => Promise<unknown>, post = vi.fn(async () => SOURCE), speech?: LocalSpeech, podcastAudio?: PodcastAudio) {
  let clear = () => {};
  const wrappedPost = vi.fn(async (path: string, ...args: unknown[]) => path.endsWith("/journey") ? { journey: null } : path.startsWith("/v1/study/retries/") ? { client_key: `cli_${"0".repeat(26)}`, expires_at: "2099-10-18T00:05:00Z" } : (post as unknown as (path: string, ...args: unknown[]) => Promise<unknown>)(path, ...args));
  const commands = { get: vi.fn(async (path: string) => path.endsWith("/saved-result") ? { result: null } : get(path)), post: wrappedPost, request: vi.fn(async (method: string, path: string, body: unknown, key: string, headers: unknown) => path.endsWith("/journey") ? { journey: null } : (post as unknown as (path: string, ...args: unknown[]) => Promise<unknown>)(path, body, key, headers)), delete: vi.fn(async () => undefined), scoped: vi.fn() };
  commands.scoped.mockImplementation(() => commands);
  const profiles = { generation: 1, commands, onClear: (fn: () => void) => { clear = fn; }, getView: () => ({ settings: null }) };
  const controller = new StudyWorkspaceController(profiles as unknown as ProfileController, speech, podcastAudio);
  return { controller, profiles, clear: () => { profiles.generation++; clear(); } };
}
test.each(["rejected", "short"])("an unreadable picker file (%s) shows a file error before creating any source", async (failure) => {
  const fake = setup(async () => ({}));
  const file = new File(["synthetic PDF"], "notes.pdf", { type: "application/pdf" });
  vi.stubGlobal("FileReader", undefined);
  Object.defineProperty(file, "arrayBuffer", { value: failure === "rejected" ? async () => { throw new DOMException("unreadable", "NotReadableError"); } : async () => new ArrayBuffer(0) });
  try {
    await fake.controller.upload(file);
    expect(fake.controller.getView()).toMatchObject({ busy: false, uploadReading: false, error: "file_read_failed", source: null });
    expect(fake.profiles.commands.post).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});
test("a stalled picker read times out and a later read cannot start an upload", async () => {
  const fake = setup(async () => ({}));
  let finish!: (bytes: ArrayBuffer) => void;
  const file = new File(["synthetic PDF"], "notes.pdf");
  vi.stubGlobal("FileReader", undefined);
  Object.defineProperty(file, "arrayBuffer", { value: () => new Promise<ArrayBuffer>((resolve) => { finish = resolve; }) });
  vi.useFakeTimers();
  try {
    const pending = fake.controller.upload(file);
    expect(fake.controller.getView()).toMatchObject({ busy: true, uploadReading: true });
    await vi.advanceTimersByTimeAsync(15_000);
    await pending;
    expect(fake.controller.getView()).toMatchObject({ busy: false, error: "file_read_failed", source: null });
    finish(new ArrayBuffer(file.size));
    await Promise.resolve();
    expect(fake.profiles.commands.post).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
});
test("a file read finishing after a profile change cannot create a source in the new profile", async () => {
  const fake = setup(async () => ({}));
  let finish!: (bytes: ArrayBuffer) => void;
  const file = new File(["synthetic PDF"], "notes.pdf");
  vi.stubGlobal("FileReader", undefined);
  Object.defineProperty(file, "arrayBuffer", { value: () => new Promise<ArrayBuffer>((resolve) => { finish = resolve; }) });
  try {
    const pending = fake.controller.upload(file);
    fake.clear();
    finish(new ArrayBuffer(file.size));
    await pending;
    expect(fake.controller.getView()).toEqual(EMPTY_STUDY);
    expect(fake.profiles.commands.post).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});
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

test.each([["chat", "chat"], ["flashcards", "chat"], ["quiz", "chat"], ["quiz", "flashcards"]] as const)("%s follow-up from %s keeps its parent and original source selections", async (kind, parentKind) => {
  const deckId = `dek_${"0".repeat(26)}`;
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: parentKind, title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA stores genetic information.")], status: "ready", created_at: now, ...(parentKind === "flashcards" ? { deck_id: deckId } : {}) };
  const post = vi.fn(async (path: string) => path.endsWith("/open") ? GRANT : { job_id: `stj_${"1".repeat(26)}`, kind, sources: aid.sources, state: "queued", completed_units: 0, total_units: null, result_ids: [], error: null, created_at: now, updated_at: now });
  const fake = setup(async (path) => path === `/v1/study/aids/${AID}` ? aid : path === `/v1/study/decks/${deckId}` ? { deck_id: deckId, aid_id: AID, source_id: sid, revision: 1, scheduler: "fsrs-6-source-v1", cards: [{ card_id: `fcd_${"0".repeat(26)}`, revision: 1, suspended: false, front: cite("DNA?"), back: cite("DNA") }] } : { items: [], next_cursor: null }, post as never);
  await fake.controller.open(sid); await fake.controller.showAid(AID);
  await fake.controller.generate(kind, 10, false, true, kind === "chat" ? "Explain that step again." : undefined, undefined, AID);
  expect(post).toHaveBeenLastCalledWith("/v1/study/jobs", expect.objectContaining({ kind, context_aid_id: AID, sources: aid.sources }), expect.stringMatching(/^cli_/), expect.anything());
  expect(fake.controller.getView().error).toBeNull();
});

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

test.each(["chat", "summary", "flashcards", "quiz"])("a newly requested %s opens its complete result once, after completion", async (kind) => {
  const jobId = `stj_${"2".repeat(26)}`, aidId = `aid_${"2".repeat(26)}`;
  const job = { job_id: jobId, kind, sources: [{ source_id: sid, revision: 1 }], state: "queued", completed_units: 0, total_units: 1, result_ids: [], error: null, created_at: now, updated_at: now };
  const answer = { aid_id: aidId, job_id: jobId, kind, prompt: "What is DNA?", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [{ text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] }], status: "ready", created_at: now, ...(kind === "flashcards" ? { deck_id: `dek_${"2".repeat(26)}` } : {}), ...(kind === "quiz" ? { quiz_id: `sqz_${"2".repeat(26)}` } : {}) };
  let ready = false;
  const post = vi.fn(async (path: string) => path === "/v1/study/jobs" ? job : { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" });
  const fake = setup(async (path) => {
    if (path === "/v1/study/workspace") return { sources: { items: [SOURCE], next_cursor: null }, jobs: [] };
    if (path === `/v1/study/sources/${sid}`) return SOURCE;
    if (path === `/v1/study/aids/${aidId}`) return answer;
    if (path.startsWith("/v1/study/decks/")) return { deck_id: answer.deck_id, aid_id: aidId, source_id: sid, revision: 1, scheduler: "fsrs-6-source-v1", cards: [{ card_id: `fcd_${"2".repeat(26)}`, revision: 1, suspended: false, front: cite("DNA?"), back: cite("DNA") }] };
    if (path.startsWith("/v1/study/quizzes/")) return { quiz_id: answer.quiz_id, aid_id: aidId, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cite("DNA") }] };
    return { items: path.startsWith("/v1/study/aids?") && ready ? [answer] : [], next_cursor: null };
  }, post as never);
  await fake.controller.open(sid);
  await fake.controller.generate(kind as "chat" | "summary" | "flashcards" | "quiz", 10, false, false, "What is DNA?");
  await fake.controller.refreshOpened();
  expect(fake.controller.getView().aid).toBeNull(); // still working
  ready = true; await fake.controller.refreshOpened();
  expect(fake.controller.getView().aid?.aid_id).toBe(aidId);
  if (kind === "flashcards") expect(fake.controller.getView().deck?.deck_id).toBe(answer.deck_id);
  if (kind === "quiz") expect(fake.controller.getView().quiz?.quiz_id).toBe(answer.quiz_id);
  fake.controller.hideAid(); await fake.controller.refreshOpened();
  expect(fake.controller.getView().aid).toBeNull(); // no unsolicited reopening
});


test.each(["finish", "stop_pending", "profile_clear"])("NVIDIA Podcast %s never uses system synthesis or plays a late response", async (mode) => {
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", title: "Overview", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA")], status: "ready", created_at: now };
  let release: ((value: Blob) => void) | undefined;
  const pendingAudio = new Promise<Blob>((resolve) => { release = resolve; });
  const local: LocalSpeech = { available: () => false, subscribe: () => () => {}, speak: vi.fn() };
  const audio: PodcastAudio = { available: () => true, activate: vi.fn(), play: vi.fn((_blob, _rate, callbacks) => { void Promise.resolve().then(callbacks.end); return vi.fn(); }) };
  const post = vi.fn(async () => mode === "finish" ? new Blob([new Uint8Array(52)], { type: "audio/wav" }) : pendingAudio);
  const fake = setup(async (path) => {
    if (path === "/v1/study/podcast-voice") return { enabled: true, configured: true, provider: "nvidia_magpie" };
    if (path.includes("/speech?")) return { aid_id: AID, claim_index: 0, text: "DNA", next_offset: null, last_claim: true };
    return aid;
  }, post as never, local, audio);
  await fake.controller.showAid(AID);
  expect(fake.controller.getView().canSpeak).toBe(true);
  const playback = fake.controller.playOverview();
  await vi.waitFor(() => expect(post).toHaveBeenCalled());
  if (mode !== "finish") {
    if (mode === "profile_clear") fake.clear(); else fake.controller.stopReading();
    release!(new Blob([new Uint8Array(52)], { type: "audio/wav" }));
  }
  await playback;
  expect(local.speak).not.toHaveBeenCalled();
  expect(audio.activate).toHaveBeenCalledOnce();
  expect(audio.play).toHaveBeenCalledTimes(mode === "finish" ? 1 : 0);
  expect(fake.controller.getView().reading).toBe(false);
  if (mode === "finish") expect(fake.controller.getView().audioCompleted).toBe(true);
  const request = post.mock.calls[0] as unknown as [string, { text?: string; nvidia_consent: boolean; text_sha256: string }];
  expect(request[0]).toContain("/neural-speech");
  expect(request[1].nvidia_consent).toBe(true);
  expect(request[1].text_sha256).toHaveLength(64);
  expect(request[1].text).toBeUndefined(); // script is selected again by the native core
});


test("NVIDIA failure is visible and never silently falls back to an available robotic system voice", async () => {
  const { CommandError } = await import("../src/stream/commands.js");
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", title: "Overview", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA")], status: "ready", created_at: now };
  const local: LocalSpeech = { available: () => true, subscribe: () => () => {}, speak: vi.fn() };
  const audio: PodcastAudio = { available: () => true, activate: vi.fn(), play: vi.fn() };
  const fake = setup(async (path) => {
    if (path === "/v1/study/podcast-voice") return { enabled: true, configured: true, provider: "nvidia_magpie" };
    if (path.includes("/speech?")) return { aid_id: AID, claim_index: 0, text: "DNA", next_offset: null, last_claim: true };
    return aid;
  }, vi.fn(async () => { throw new CommandError(503, "validation_failed", false, { reason: "neural_speech_unavailable" }); }) as never, local, audio);
  await fake.controller.showAid(AID);
  await fake.controller.playOverview();
  expect(local.speak).not.toHaveBeenCalled();
  expect(audio.play).not.toHaveBeenCalled();
  expect(fake.controller.getView()).toMatchObject({ reading: false, audioPreparing: false, error: "neural_speech_unavailable" });
});

test("NVIDIA buffers only one passage ahead; Pause holds the next passage and Stop drops it", async () => {
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", title: "Overview", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA"), cite("RNA"), cite("Enzymes")], status: "ready", created_at: now };
  const ended: (() => void)[] = [], cancelled = vi.fn();
  const audio: PodcastAudio = { available: () => true, activate: vi.fn(), pause: vi.fn(), resume: vi.fn(), play: vi.fn((_blob, _rate, cb) => { ended.push(cb.end); return cancelled; }) };
  const post = vi.fn(async () => new Blob([new Uint8Array(52)], { type: "audio/wav" }));
  const fake = setup(async (path) => {
    if (path === "/v1/study/podcast-voice") return { enabled: true, configured: true, provider: "nvidia_magpie" };
    if (path.includes("/speech?")) { const n = Number(new URL(path, "http://core.test").searchParams.get("claim")); return { aid_id: AID, claim_index: n, text: ["DNA", "RNA", "Enzymes"][n], next_offset: null, last_claim: n === 2 }; }
    return aid;
  }, post as never, undefined, audio);
  await fake.controller.showAid(AID);
  const playback = fake.controller.playOverview();
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(audio.play).toHaveBeenCalledTimes(1); // second request overlaps first audio, no third speculative send
  fake.controller.pauseOverview(); ended[0]!();
  await Promise.resolve(); await Promise.resolve();
  expect(fake.controller.getView().audioPaused).toBe(true);
  expect(audio.play).toHaveBeenCalledTimes(1);
  fake.controller.resumeOverview();
  await vi.waitFor(() => expect(audio.play).toHaveBeenCalledTimes(2));
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(3));
  fake.controller.stopReading();
  await playback;
  expect(cancelled).toHaveBeenCalledOnce();
  expect(audio.play).toHaveBeenCalledTimes(2);
  expect(fake.controller.getView()).toMatchObject({ reading: false, audioPaused: false, audioCompleted: false });
});

test("checking one quiz question sends no other answers and keeps the whole-quiz result separate", async () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "quiz", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA")], status: "ready", created_at: now, quiz_id: quizId };
  const feedback = { item_id: "q1", verdict: "correct", marking: "judged", label: "Judged, not checked", explanation: cite("DNA") };
  const post = vi.fn(async () => ({ attempt_id: `sqa_${"0".repeat(26)}`, results: [feedback, { item_id: "q2", verdict: "skipped" }] }));
  const fake = setup(async (path) => path.includes("/quizzes/") ? { quiz_id: quizId, aid_id: AID, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cite("DNA") }, { item_id: "q2", type: "true_false", stem: cite("RNA") }] } : aid, post as never);
  await fake.controller.showAid(AID); await fake.controller.checkAnswer("q1", "true");
  expect(post).toHaveBeenLastCalledWith(`/v1/study/quizzes/${quizId}/attempts`, expect.objectContaining({ answers: [{ item_id: "q1", answer: "true" }] }), expect.any(String), expect.anything());
  expect(fake.controller.getView().quizFeedback).toEqual({ q1: feedback });
  expect(fake.controller.getView().result).toBeNull();
});

test("a failed speculative speech request is observed, never retried, and reported after current audio ends", async () => {
  const { CommandError } = await import("../src/stream/commands.js");
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", title: "Overview", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA"), cite("RNA")], status: "ready", created_at: now };
  let end = () => {};
  const audio: PodcastAudio = { available: () => true, activate: vi.fn(), play: vi.fn((_blob, _rate, cb) => { end = cb.end; return vi.fn(); }) };
  const post = vi.fn(async () => { if (post.mock.calls.length > 1) throw new CommandError(503, "validation_failed", false, { reason: "neural_speech_unavailable" }); return new Blob([new Uint8Array(52)], { type: "audio/wav" }); });
  const fake = setup(async (path) => {
    if (path === "/v1/study/podcast-voice") return { enabled: true, configured: true, provider: "nvidia_magpie" };
    if (path.includes("/speech?")) { const n = Number(new URL(path, "http://core.test").searchParams.get("claim")); return { aid_id: AID, claim_index: n, text: n ? "RNA" : "DNA", next_offset: null, last_claim: n === 1 }; }
    return aid;
  }, post as never, undefined, audio);
  await fake.controller.showAid(AID); const playback = fake.controller.playOverview();
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(fake.controller.getView().reading).toBe(true);
  end(); await playback;
  expect(fake.controller.getView()).toMatchObject({ error: "neural_speech_unavailable", reading: false, audioCompleted: false });
  expect(post).toHaveBeenCalledTimes(2); expect(audio.play).toHaveBeenCalledOnce();
});

test("Resume rechecks native permission and cancels buffered audio if Study consent was withdrawn", async () => {
  const { CommandError } = await import("../src/stream/commands.js");
  const aid = { aid_id: AID, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", title: "Overview", sources: [{ source_id: sid, revision: 1 }], claims: [cite("DNA"), cite("RNA")], status: "ready", created_at: now };
  let allowed = true;
  const cancelled = vi.fn(), audio: PodcastAudio = { available: () => true, activate: vi.fn(), pause: vi.fn(), resume: vi.fn(), play: vi.fn(() => cancelled) };
  const fake = setup(async (path) => {
    if (path === "/v1/study/podcast-voice") return { enabled: true, configured: true, provider: "nvidia_magpie" };
    if (path.includes("/speech?")) {
      if (!allowed) throw new CommandError(403, "validation_failed", false, { reason: "consent_required" });
      const n = Number(new URL(path, "http://core.test").searchParams.get("claim"));
      return { aid_id: AID, claim_index: n, text: n ? "RNA" : "DNA", next_offset: null, last_claim: n === 1 };
    }
    return aid;
  }, vi.fn(async () => new Blob([new Uint8Array(52)], { type: "audio/wav" })) as never, undefined, audio);
  await fake.controller.showAid(AID); const playback = fake.controller.playOverview();
  await vi.waitFor(() => expect(audio.play).toHaveBeenCalledOnce());
  fake.controller.pauseOverview(); allowed = false;
  await fake.controller.resumeOverview(); await playback;
  expect(cancelled).toHaveBeenCalledOnce(); expect(audio.play).toHaveBeenCalledOnce();
  expect(fake.controller.getView()).toMatchObject({ reading: false, audioPaused: false, error: "consent_required" });
});

test("library archive restores by metadata only and cannot leak a late result across profile switches", async () => {
  let archived: string[] = [];
  const post = vi.fn(async () => ({ archived_source_ids: archived = archived.length ? [] : [sid] }));
  const fake = setup(async (path) => path === "/v1/study/library" ? { archived_source_ids: archived } : path === "/v1/study/workspace" ? { sources: { items: [SOURCE], next_cursor: null }, jobs: [] } : { items: [], next_cursor: null }, post as never);
  await fake.controller.archiveSources([sid], true);
  expect(fake.profiles.commands.request).toHaveBeenLastCalledWith("POST", `/v1/study/sources/${sid}/archive`, {}, expect.stringMatching(/^cli_/), {});
  expect(fake.controller.getView().archivedSourceIds).toEqual([sid]);
  expect(fake.controller.getView().sources).toEqual([SOURCE]);
  await fake.controller.archiveSources([sid], false);
  expect(fake.profiles.commands.request).toHaveBeenLastCalledWith("DELETE", `/v1/study/sources/${sid}/archive`, {}, expect.stringMatching(/^cli_/), {});
  expect(fake.controller.getView().archivedSourceIds).toEqual([]);
  fake.clear();
  expect(fake.controller.getView()).toEqual(EMPTY_STUDY);

  let release!: (value: unknown) => void;
  const latePost = vi.fn(() => new Promise((resolve) => { release = resolve; }));
  const late = setup(async () => ({ sources: { items: [], next_cursor: null }, jobs: [] }), latePost as never);
  const pending = late.controller.archiveSources([sid, `src_${"1".repeat(26)}`], true);
  await vi.waitFor(() => expect(latePost).toHaveBeenCalledOnce());
  late.clear(); release({ archived_source_ids: [sid] }); await pending;
  expect(latePost).toHaveBeenCalledOnce();
  expect(late.controller.getView()).toEqual(EMPTY_STUDY);
});

test("contextual quiz coaching preserves the quiz draft, binds the selected item and clears on profile change", async () => {
  const quizId = `sqz_${"0".repeat(26)}`, aidId = `aid_${"0".repeat(26)}`, helpId = `aid_${"1".repeat(26)}`, jobId = `stj_${"1".repeat(26)}`;
  const cite = { text: "Think about the relationship described in the material.", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] };
  const aid = { aid_id: aidId, job_id: `stj_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId, sources: [{ source_id: sid, revision: 1 }], title: "Biology", claims: [cite], status: "ready", created_at: now };
  const quiz = { quiz_id: quizId, aid_id: aidId, revision: 1, status: "ready", draft: { quiz_revision: 1, position: 0, answers: [{ item_id: "q1", answer: "a" }] }, items: [{ item_id: "q1", type: "choice", stem: { ...cite, text: "What stores genetic information?" }, options: [{ option_id: "a", text: "DNA" }, { option_id: "b", text: "Water" }] }] };
  const job = { job_id: jobId, kind: "chat", sources: aid.sources, state: "queued", completed_units: 0, total_units: null, result_ids: [], error: null, created_at: now, updated_at: now };
  const helpAid = { ...aid, aid_id: helpId, job_id: jobId, kind: "chat", quiz_id: undefined };
  let finished = false;
  const post = vi.fn(async (path: string) => path.endsWith("/open") ? { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" } : job);
  const fake = setup(async (path) => {
    if (path === "/v1/study/workspace") return { sources: { items: [SOURCE], next_cursor: null }, jobs: [{ ...job, state: finished ? "completed" : "queued", result_ids: finished ? [helpId] : [] }] };
    if (path === `/v1/study/sources/${sid}`) return SOURCE;
    if (path === `/v1/study/aids/${aidId}`) return aid;
    if (path === `/v1/study/quizzes/${quizId}`) return quiz;
    if (path.startsWith("/v1/study/aids?")) return { items: [aid, ...(finished ? [helpAid] : [])], next_cursor: null };
    return { items: [], next_cursor: null };
  }, post as never);
  await fake.controller.open(sid); await fake.controller.showAid(aidId);
  await fake.controller.requestQuizHelp("q1", "hint");
  const body = fake.profiles.commands.request.mock.calls.find((call) => call[1] === `/v1/study/quizzes/${quizId}/items/q1/help`)![2] as Record<string, unknown>;
  expect(body).toMatchObject({ kind: "chat", execution: "prefer_cloud", sources: aid.sources, prompt: expect.stringContaining("What stores genetic information?") });
  expect(body.prompt).toContain("Do not reveal the answer");
  expect(body.prompt).toContain("1. DNA\n2. Water");
  expect(body).not.toHaveProperty("answer");
  expect(fake.controller.getView().quiz).toEqual(quiz);
  expect(fake.controller.getView().aid?.aid_id).toBe(aidId);
  const calls = post.mock.calls.length;
  await fake.controller.requestQuizHelp("q1", "walk_through");
  expect(post).toHaveBeenCalledTimes(calls); // duplicate clicks cannot queue overlapping help
  finished = true; await fake.controller.refreshOpened();
  expect(fake.controller.getView().quizHelp?.aid?.aid_id).toBe(helpId);
  expect(fake.controller.getView().quiz?.draft).toEqual(quiz.draft);
  expect(fake.controller.getView().aid?.aid_id).toBe(aidId);
  await fake.controller.requestQuizHelp("q1", "walk_through", true, "What is the next reasoning step?");
  expect(fake.profiles.commands.request).toHaveBeenLastCalledWith("POST", `/v1/study/quizzes/${quizId}/items/q1/help`, expect.objectContaining({ confirm_readable_only: true, prompt: expect.stringContaining("only the next reasoning step") }), expect.any(String), expect.any(Object));
  const follow = fake.profiles.commands.request.mock.calls.at(-1)![2] as { prompt: string };
  expect(follow.prompt.startsWith("Answer my follow-up ONLY")).toBe(true);
  expect(follow.prompt).not.toContain("Walk me through this practice question");
  expect(follow.prompt.indexOf("What is the next reasoning step?")).toBeLessThan(follow.prompt.indexOf("Quiz context"));
  expect(follow.prompt.length).toBeLessThanOrEqual(4000);
  fake.clear();
  expect(fake.controller.getView()).toEqual(EMPTY_STUDY);
});

test.each([1, 2])("saved journey restores submitted results and the exact revision when current revision is %i", async (latestRevision) => {
  const root = `aid_${"1".repeat(26)}`, aidId = `aid_${"2".repeat(26)}`, quizId = `sqz_${"2".repeat(26)}`;
  const claim = { text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] };
  const aid = { aid_id: aidId, job_id: `stj_${"2".repeat(26)}`, kind: "quiz", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [claim], status: "ready", created_at: now, quiz_id: quizId };
  const quiz = { quiz_id: quizId, aid_id: aidId, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: claim }] };
  const result = { attempt_id: `sqa_${"2".repeat(26)}`, results: [{ item_id: "q1", verdict: "correct", marking: "judged", label: "Judged, not checked", explanation: claim }] };
  const journey = { root_aid_id: root, lesson_aid_id: root, cards_aid_id: null, quiz_aid_id: aidId, next_aid_id: aidId, title: "Biology", sources: aid.sources, phase: "complete", cards_reviewed: 0, cards_total: 0, cards_due: 0, review_card_ids: [], questions_answered: 1, questions_total: 1, questions_correct: 1, questions_to_review: 0, retry_quiz: false, next_review_at: null };
  const post = vi.fn(async (path: string) => path.endsWith("/open") ? { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" } : { journey });
  const fake = setup(async () => null, post as never);
  fake.profiles.commands.get.mockImplementation(async (path: string) => {
    if (path === "/v1/study/workspace") return { sources: { items: [{ ...SOURCE, revision: latestRevision }], next_cursor: null }, jobs: [], journey };
    if (path === "/v1/study/sets") return { items: [], next_cursor: null };
    if (path.includes("/content?") || path.includes("/aids?")) return { items: [], next_cursor: null };
    if (path.endsWith("/saved-result")) return { result, answers: [{ item_id: "q1", answer: "true" }] };
    if (path.includes("/quizzes/")) return quiz;
    if (path.includes("/aids/")) return aid;
    return { archived_source_ids: [] };
  });
  fake.profiles.commands.request.mockImplementation(async (_method, path) => path.endsWith("/open") ? post(path) : { journey });
  await fake.controller.load();
  expect(fake.controller.getView().journey).toEqual(journey);
  await fake.controller.continueJourney();
  expect(fake.controller.getView()).toMatchObject({ error: null, source: SOURCE, aid, quiz, result, journey });
  expect(fake.controller.getView().resultAnswers).toEqual({ q1: "true" });
  expect(fake.profiles.commands.post).toHaveBeenCalledWith(`/v1/study/sources/${sid}/open`, { confirm: true, ...(latestRevision === 1 ? {} : { revision: 1 }) }, expect.any(String));
  expect(fake.controller.getView().followCurrent).toBe(latestRevision === 1);
  expect(fake.profiles.commands.request.mock.calls.some(([, path]) => path.includes("/jobs") || path.endsWith("/attempts"))).toBe(false);
  fake.clear();
  expect(fake.controller.getView()).toEqual(EMPTY_STUDY);
});

test.each([false, true])("due review restores a removed card before untouched cards and respects profile changes: %s", async (clearDuringRead) => {
  vi.useFakeTimers();
  try {
  const root = `aid_${"1".repeat(26)}`, aidId = `aid_${"2".repeat(26)}`, deckId = `dek_${"2".repeat(26)}`, cardId = `fcd_${"2".repeat(26)}`;
  const claim = { text: "DNA", citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] };
  const aid = { aid_id: aidId, job_id: `stj_${"2".repeat(26)}`, kind: "flashcards", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [claim], status: "ready", created_at: now, deck_id: deckId };
  const card = { card_id: cardId, revision: 1, front: claim, back: claim, suspended: false };
  const untouched = { ...card, card_id: `fcd_${"3".repeat(26)}` };
  const deck = { deck_id: deckId, aid_id: aidId, source_id: sid, revision: 1, scheduler: "fsrs-6-source-v1", cards: [card, untouched] };
  let due = true, deckReads = 0;
  const journey = () => ({ root_aid_id: root, lesson_aid_id: root, cards_aid_id: aidId, quiz_aid_id: null, next_aid_id: aidId, title: "Biology", sources: aid.sources, phase: "flashcards", cards_reviewed: 1, cards_total: 2, cards_due: Number(due) + 1, review_card_ids: due ? [cardId, untouched.card_id] : [untouched.card_id], questions_answered: 0, questions_total: 0, questions_correct: 0, questions_to_review: 0, retry_quiz: false, next_review_at: Date.now() + 120_000 });
  const post = vi.fn(async (path: string) => {
    if (path.endsWith("/open")) return { source: SOURCE, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" };
    if (path.endsWith("/reviews")) {
      due = false;
      return { client_review_id: `srv_${"0".repeat(26)}`, due_at: new Date(Date.now() + 120_000).toISOString(), scheduler: "fsrs-6-source-v1", stability: 1, difficulty: 5, reps: 2, lapses: 1 };
    }
    return { journey: journey() };
  });
  const fake = setup(async () => null, post as never);
  fake.profiles.commands.get.mockImplementation(async (path: string) => {
    if (path === "/v1/study/workspace") return { sources: { items: [SOURCE], next_cursor: null }, jobs: [], journey: journey() };
    if (path === "/v1/study/sets" || path.includes("/content?") || path.includes("/aids?")) return { items: [], next_cursor: null };
    if (path.includes("/decks/")) { deckReads++; if (clearDuringRead && deckReads === 2) fake.clear(); return deck; }
    if (path.includes("/aids/")) return aid;
    return { archived_source_ids: [] };
  });
  fake.profiles.commands.request.mockImplementation(async (_method, path) => post(path));
  await fake.controller.load(); await fake.controller.continueJourney();
  expect(fake.controller.getView().deck?.cards).toHaveLength(2);
  await fake.controller.rate(card, "again");
  expect(fake.controller.getView().deck?.cards).toEqual([untouched]);
  await vi.advanceTimersByTimeAsync(119_999);
  expect(fake.controller.getView().deck?.cards).toEqual([untouched]);
  due = true;
  await vi.advanceTimersByTimeAsync(51);
  if (clearDuringRead) expect(fake.controller.getView()).toEqual(EMPTY_STUDY);
  else {
    expect(fake.controller.getView().deck?.cards.map((c) => c.card_id)).toEqual([cardId, untouched.card_id]);
    await fake.controller.refreshDueReview();
    expect(fake.controller.getView().deck?.cards).toHaveLength(2);
    expect(deckReads).toBe(2);
  }
  expect(fake.profiles.commands.request.mock.calls.filter(([, path]) => path.endsWith("/reviews"))).toHaveLength(1);
  fake.clear();
  } finally { vi.useRealTimers(); }
});

test.each(["error", "timeout"])("native FileReader %s releases the upload and reports a useful error", async (failure) => {
  const fake = setup(async () => ({}));
  const abort = vi.fn();
  const readers: FailedReader[] = [];
  class FailedReader {
    onload = null; onerror: (() => void) | null = null; onabort = null;
    abort = abort;
    readAsArrayBuffer() { readers.push(this); if (failure === "error") this.onerror?.(); }
  }
  vi.stubGlobal("FileReader", FailedReader); vi.useFakeTimers();
  try {
    const pending = fake.controller.upload(new File(["scan"], "scan.pdf"));
    if (failure === "timeout") await vi.advanceTimersByTimeAsync(15_000);
    await pending;
    expect(fake.controller.getView()).toMatchObject({ busy: false, uploadReading: false, error: "file_read_failed" });
    expect(fake.profiles.commands.post).not.toHaveBeenCalled();
    expect(readers[0]).toMatchObject({ onload: null, onerror: null, onabort: null });
    expect(abort).toHaveBeenCalledTimes(failure === "timeout" ? 1 : 0);
  } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
});

test("a source whose chunk upload failed stays visible and can be resumed", async () => {
  const uploading = { ...SOURCE, kind: "pdf", state: "uploading", readable_units: 0 };
  const post = vi.fn(async (path: string) => {
    if (path.includes("/chunks/")) throw new Error("connection lost");
    if (path.endsWith("/open")) return { source: uploading, open_token: "t".repeat(43), expires_at: "2099-10-18T00:05:00Z" };
    return uploading;
  });
  const fake = setup(async (path) => path === "/v1/study/workspace" ? { sources: { items: [uploading], next_cursor: null }, jobs: [] } : { items: [], next_cursor: null }, post as never);
  await fake.controller.upload(new File(["synthetic PDF"], "notes.pdf"));
  expect(fake.controller.getView()).toMatchObject({ source: uploading, sources: [uploading], error: "unreachable", busy: false });
  expect(post).not.toHaveBeenCalledWith("/v1/study/jobs", expect.anything(), expect.anything(), expect.anything());
});
