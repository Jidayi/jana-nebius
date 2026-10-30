// SEC-19, API-23, D86/D87 (client half): the core closes a profile after its inactivity window counted in profile
// requests, and a restarted core has no tokens at all. While the student is using the app, the profile is opened again
// at once with no PIN and the request that found it closed goes through; the open session's stream reconnects instead
// of stopping. After the window with no activity the profile closes here too and the picker says why. Reopening a
// profile continues its newest session for the same subject and topic (`GET /v1/sessions`) instead of starting again.
import { describe, expect, test } from "vitest";
import { ProfileController, type ProfileTimers } from "../src/profiles.js";
import { SessionController, StoreHolder } from "../src/session.js";
import { firstRunProfile, installedSubjects, subjectName } from "../src/setup.js";
import { tutorAnswers, unverifiedSubjects } from "../src/health.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const ADA = PROFILES[0]!;

async function until(check: () => boolean, timeoutMs = 5_000): Promise<void> {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 5));
  }
}

/** A clock and timers the test moves by hand. */
function manualTime() {
  let now = 1_000_000;
  const pending = new Map<number, { at: number; fn: () => void }>();
  let next = 0;
  const timers: ProfileTimers = {
    setTimeout: (fn, ms) => {
      next += 1;
      pending.set(next, { at: now + ms, fn });
      return next;
    },
    clearTimeout: (handle) => void pending.delete(handle as number),
  };
  const advance = (ms: number) => {
    now += ms;
    for (const [id, timer] of [...pending].sort((a, b) => a[1].at - b[1].at)) {
      if (timer.at > now) continue;
      pending.delete(id);
      timer.fn();
    }
  };
  return { timers, now: () => now, advance, jump: (ms: number) => void (now += ms) };
}

async function opened(time = manualTime()) {
  const core = new FakeProfileCore();
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch, now: time.now, timers: time.timers });
  await profiles.load();
  expect(await profiles.unlock(ADA.profile_id)).toBe(true);
  return { core, profiles, time };
}

const opens = (core: FakeProfileCore) => core.log.filter((r) => r.path === `/v1/profiles/${ADA.profile_id}/open`).length;

describe("SEC-19", () => {
  test("automatic recovery does not take a profile back from another window", async () => {
    const core = new FakeProfileCore();
    core.singleActiveProfile = true;
    const older = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    const newer = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
    await older.load();
    await newer.load();
    expect(await older.unlock(ADA.profile_id)).toBe(true);
    expect(await newer.unlock(PROFILES[1]!.profile_id)).toBe(true);
    await expect(older.loadSettings()).rejects.toMatchObject({ code: "profile_token_expired" });
    expect(older.getView().active).toBeNull();
    expect(newer.getView().active).toBe(PROFILES[1]!.profile_id);
    await expect(newer.loadSettings()).resolves.toBeDefined();
    expect(opens(core)).toBe(2); // one picker action, one refused recovery; no renewal loop
    await newer.lock();
  });

  test("test_sec19_closed_profile_reopens_while_the_student_is_active", async () => {
    const { core, profiles, time } = await opened();
    const generation = profiles.generation;
    time.advance(9 * 60_000);
    profiles.noteActivity(); // reading and typing: no profile request, but the student is here
    core.expireTokens(); // the core's idle auto-lock (or a restart) closed the profile
    const settings = await profiles.loadSettings();
    expect(settings.memory_saving).toBe(true);
    expect(opens(core)).toBe(2); // opened again once, with no PIN and no body
    expect(core.log.filter((r) => r.path.endsWith("/open")).every((r) => JSON.stringify(r.body) === "{}")).toBe(true);
    expect(profiles.getView().active).toBe(ADA.profile_id);
    expect(profiles.generation).toBe(generation); // nothing was cleared: the open session carries on
  });

  test("test_sec19_session_stream_reconnects_after_the_core_closed_the_profile", async () => {
    const { core, profiles } = await opened(); // real timers for the stream's backoff
    const holder = profiles.holder;
    await SessionController.create(profiles.launch, { mode: "guided", subject: "physics", level: "O", origin: { kind: "ask", ref: null } }, { fetch: core.fetch });
    const session = new SessionController(profiles.launch, holder, ADA.session_id, { fetch: core.fetch });
    let lost = 0;
    session.onAuthLost(() => (lost += 1));
    await session.open();
    await until(() => core.openStreams === 1);
    // The core restarts: every token is gone and the live stream ends. The stream finds the profile closed, the
    // profile is opened again, and the stream is back (before this fix it stopped for good, silently).
    const before = core.log.filter((r) => r.path.endsWith("/events")).length;
    core.expireTokens();
    core.dropStreams();
    await until(() => core.log.filter((r) => r.path.endsWith("/events")).length >= before + 2 && core.openStreams === 1);
    expect(opens(core)).toBe(2);
    expect(lost).toBe(0);
    expect(profiles.getView().active).toBe(ADA.profile_id);
    session.close();
  });

  test("test_sec19_idle_profile_closes_and_the_picker_says_why", async () => {
    const { core, profiles, time } = await opened();
    let cleared = 0;
    profiles.onClear(() => (cleared += 1));
    time.advance(5 * 60_000);
    profiles.noteActivity();
    time.advance(9 * 60_000); // the timer fires at 10 min, sees activity at 5 min and waits out the rest
    expect(profiles.getView().active).toBe(ADA.profile_id);
    time.advance(60_000 + 1);
    await until(() => profiles.getView().active === null);
    expect(profiles.getView().ended).toBe("profile_token_expired");
    expect(cleared).toBe(1);
    expect(core.log.some((r) => r.path.endsWith("/close"))).toBe(true);
    // Opening again is a tap, and the notice goes.
    expect(await profiles.unlock(ADA.profile_id)).toBe(true);
    expect(profiles.getView().ended).toBeNull();
  });

  test("test_sec19_no_reopen_after_the_window_without_activity", async () => {
    const { core, profiles, time } = await opened();
    core.expireTokens();
    // The laptop slept: the clock moved past the window with no activity and the timer has not run yet. A request
    // that then finds the profile closed does not open it silently.
    time.jump(11 * 60_000);
    await expect(profiles.loadSettings()).rejects.toMatchObject({ code: "profile_token_expired" });
    expect(profiles.getView().active).toBeNull();
    expect(profiles.getView().ended).toBe("profile_token_expired");
    expect(opens(core)).toBe(1);
  });

  test("test_sec19_reopen_refused_ends_the_profile", async () => {
    const { core, profiles } = await opened();
    core.expireTokens();
    core.profiles.splice(0, 1); // the profile was removed elsewhere: it cannot be opened again
    await expect(profiles.loadSettings()).rejects.toMatchObject({ code: "profile_token_expired" });
    expect(profiles.getView().active).toBeNull();
    expect(profiles.getView().ended).toBe("profile_token_expired");
  });
});

describe("API-23", () => {
  test("test_api23_reopened_profile_resumes_its_session", async () => {
    const { core, profiles } = await opened();
    const target = { mode: "guided" as const, subject: "physics" as const, level: "O" as const, origin: { kind: "ask" as const, ref: null } };
    const first = await SessionController.resume(profiles.launch, target, { fetch: core.fetch });
    expect(core.log.filter((r) => r.method === "POST" && r.path === "/v1/sessions")).toHaveLength(1);
    await profiles.lock();
    expect(await profiles.unlock(ADA.profile_id)).toBe(true);
    const again = await SessionController.resume(profiles.launch, target, { fetch: core.fetch });
    expect(again).toBe(first);
    expect(core.log.filter((r) => r.method === "POST" && r.path === "/v1/sessions")).toHaveLength(1);
    // Another subject has no session yet: one is made for it.
    await SessionController.resume(profiles.launch, { ...target, subject: "accounting" }, { fetch: core.fetch });
    expect(core.log.filter((r) => r.method === "POST" && r.path === "/v1/sessions")).toHaveLength(2);
    expect((await SessionController.latest(profiles.launch, { fetch: core.fetch }))?.subject).toBe("accounting"); // the newest
  });
});

const pack = (id: string, subject: string, level: "O" | "A", ok = true) => ({ pack_id: id, subject, level, version: "0.1.0", signature_ok: ok, size_bytes: 1 });

describe("PLT-17", () => {
  test("test_plt17_first_run_defaults_follow_the_installed_packs", () => {
    const packs = [pack("pack.phy.o", "phy", "O"), pack("pack.acc.o", "acc", "O"), pack("pack.mth.a", "mth", "A"), pack("pack.chm.o", "chm", "O", false)];
    expect(installedSubjects(packs).map((s) => s.subjectId)).toEqual(["cur.mth.a", "cur.phy.o", "cur.chm.o", "cur.acc.o"]);
    const created = firstRunProfile("  Ada ", packs, 0);
    // The name is the only thing asked; everything else is TABLE PLT-17b's default.
    expect(created).toEqual({ display_name: "Ada", avatar: "avatar-1", level: "O", subjects: ["physics", "chemistry", "accounting"], age_band: "13_15" });
    expect(firstRunProfile("Ben", [pack("pack.mth.a", "mth", "A")], 1)).toMatchObject({ level: "A", subjects: ["mathematics"], avatar: "avatar-2" });
    expect(firstRunProfile("Chi", [], 8).subjects.length).toBeGreaterThan(0);
    expect(subjectName("acc")).toBe("accounting");
    expect(subjectName("accounting")).toBe("accounting");
    expect(unverifiedSubjects(packs)).toEqual(["chemistry"]);
  });
});

describe("PLT-29", () => {
  test("test_plt29_no_tutor_without_a_model_or_on_content_only", () => {
    const models = (installed: unknown[], reason = "hardware_class.mid.predicted", hardware?: Record<string, unknown>) => ({
      installed, available: [], assignment: { fast: null, strong: null }, recommended: { fast: null, strong: null, reason_key: reason }, ...(hardware ? { hardware } : {}),
    }) as never;
    const ready = { status: "ok" as const, readiness: "ready" as const, components: { runtime: "ok" as const } };
    const coreOnly = { status: "ok" as const, readiness: "core_ready" as const, components: { runtime: "down" as const } };
    expect(tutorAnswers({ health: null, models: null })).toBeNull();
    expect(tutorAnswers({ health: ready, models: models([{ model_id: "m", pack_version: "1", serving: true }]) })).toBe(true);
    expect(tutorAnswers({ health: coreOnly, models: models([]) })).toBe(false); // no tutor model installed
    expect(tutorAnswers({ health: ready, models: models([]) })).toBe(true); // a runtime is serving all the same
    expect(tutorAnswers({ health: ready, models: models([], "hardware_class.content_only.below_minimum_speed") })).toBe(false);
    expect(tutorAnswers({ health: coreOnly, models: models([], "hardware_class.content_only.below_minimum_ram", { hardware_class: "content_only", shortfalls: [], tutor_path: "online" }) })).toBe(true);
  });
});
