// SEC-19 (client half): after a profile switch, nothing of the previous profile's transcript or board is left in the
// client's memory: the store, the profile view, the open session and every registered cache are cleared, the old
// profile token is gone, and a reply for the old profile that lands after the switch is dropped.
import { describe, expect, test } from "vitest";
import { ProfileController } from "../src/profiles.js";
import { SessionController, StoreHolder } from "../src/session.js";
import { emptyStore } from "../src/store.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const [ADA, BEN] = PROFILES as [(typeof PROFILES)[number], (typeof PROFILES)[number]];

async function until(check: () => boolean, timeoutMs = 5_000): Promise<void> {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 5));
  }
}

describe("SEC-19", () => {
  test("sec19_profile_switch_clears_state", async () => {
    const core = new FakeProfileCore();
    const holder = new StoreHolder();
    const profiles = new ProfileController(core.launch, holder, { fetch: core.fetch });
    const renderCache = new Map<string, string>(); // stands for a render cache outside the store (KaTeX, UI)
    profiles.onClear(() => renderCache.clear());

    await profiles.load();
    expect(await profiles.unlock(ADA.profile_id)).toBe(true);
    const session = new SessionController(profiles.launch, holder, ADA.session_id, { fetch: core.fetch });
    profiles.onClear(() => session.close());
    await session.open();
    await until(() => core.openStreams === 1);
    await profiles.loadSettings();
    renderCache.set("tex", ADA.canary);

    const adaToken = core.tokenOf(ADA.profile_id)!;
    const memory = () => JSON.stringify({ store: holder.getState(), view: profiles.getView(), cache: [...renderCache] });
    // The canary is really there before the switch: in the transcript, the tutor's part and the board.
    const before = holder.getState();
    expect(JSON.stringify(before.messages)).toContain(ADA.canary);
    expect(JSON.stringify(before.parts)).toContain(ADA.canary);
    expect(JSON.stringify(before.boards)).toContain(ADA.canary);
    // The profile token was sent as a header, and is held nowhere a snapshot of client state could see it.
    expect(core.log.find((r) => r.path.endsWith("/snapshot"))?.headers["x-profile-token"]).toBe(adaToken);
    expect(memory()).not.toContain(adaToken);

    // A settings read for Ada that is still in flight when the switch happens.
    const release = core.hold(`/v1/profiles/${ADA.profile_id}/settings`);
    const late = profiles.loadSettings();

    expect(await profiles.unlock(BEN.profile_id)).toBe(true);
    release();
    await late.catch(() => undefined);

    expect(memory()).not.toContain(ADA.canary);
    expect(memory()).not.toContain("CANARY-ADA");
    expect(holder.getState()).toEqual(emptyStore());
    expect(profiles.getView().active).toBe(BEN.profile_id);
    expect(profiles.getView().settings).toBeNull();
    expect(renderCache.size).toBe(0);
    await until(() => core.openStreams === 0); // Ada's stream was closed with her session
    // The core was told Ada's profile ended, with her token; everything since carries Ben's token only.
    const switchAt = core.log.findIndex((r) => r.path === `/v1/profiles/${ADA.profile_id}/close`);
    expect(switchAt).toBeGreaterThan(0);
    expect(core.log[switchAt]!.headers["x-profile-token"]).toBe(adaToken);
    const unlockBen = core.log.findIndex((r) => r.path === `/v1/profiles/${BEN.profile_id}/open`);
    expect(core.log[unlockBen]!.headers["x-profile-token"]).toBeUndefined();

    // Asking for Ada's session now, with Ben unlocked, is refused and leaves the store empty of her data.
    const stale = new SessionController(profiles.launch, holder, ADA.session_id, { fetch: core.fetch });
    await expect(stale.open()).rejects.toMatchObject({ code: "not_found" });
    stale.close();
    const benSession = new SessionController(profiles.launch, holder, BEN.session_id, { fetch: core.fetch });
    profiles.onClear(() => benSession.close());
    await benSession.open();
    expect(JSON.stringify(holder.getState())).toContain(BEN.canary);
    expect(memory()).not.toContain(ADA.canary);
    await profiles.lock();
    expect(memory()).not.toContain(BEN.canary);
    expect(profiles.unlocked).toBe(false);
  });

  test("a session reply that lands after the switch is dropped", async () => {
    const core = new FakeProfileCore();
    const holder = new StoreHolder();
    const profiles = new ProfileController(core.launch, holder, { fetch: core.fetch });
    await profiles.load();
    await profiles.unlock(ADA.profile_id);
    const session = new SessionController(profiles.launch, holder, ADA.session_id, { fetch: core.fetch });
    profiles.onClear(() => session.close());
    const release = core.hold(`/v1/sessions/${ADA.session_id}/snapshot`);
    const opening = session.open().catch(() => undefined);
    await until(() => core.log.some((r) => r.path.endsWith("/snapshot")));
    await profiles.lock();
    release();
    await opening;
    expect(JSON.stringify(holder.getState())).not.toContain(ADA.canary);
  });

  test("tokens never reach web storage and family requests send no adult token", async () => {
    const writes: string[] = [];
    const storage = { setItem: (k: string) => void writes.push(k), getItem: () => null, removeItem: () => {}, clear: () => {}, key: () => null, length: 0 };
    const g = globalThis as { localStorage?: unknown; sessionStorage?: unknown };
    const saved = [g.localStorage, g.sessionStorage];
    g.localStorage = storage;
    g.sessionStorage = storage;
    try {
      const core = new FakeProfileCore();
      const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch: core.fetch });
      await profiles.load();
      await profiles.unlock(BEN.profile_id);
      await profiles.setPreferences({ easy_read: true });
      await profiles.family.setOnlineFeatures({ downloads: true });
      expect(core.log.at(-1)!.headers["x-adult-token"]).toBeUndefined();
      expect(core.log.some((r) => r.path.startsWith("/v1/adult/"))).toBe(false);
      expect(writes).toEqual([]);
    } finally {
      [g.localStorage, g.sessionStorage] = saved;
    }
  });
});
