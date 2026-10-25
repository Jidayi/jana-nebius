// TCH-12, TCH-14, UXS-33, UXS-48: the parent summary, the alerts and private session history as client-core reads them
// from the core on this computer. Each reply is checked against the shapes contract-additions-m33a.json proposes (D72):
// the local checks here agree with those definitions, and a reply that does not hold is refused. All data synthetic.
import fs from "node:fs";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import { describe, expect, test } from "vitest";
import { conversationStarter, readAlerts, readDigest, ParentController } from "../src/parents.js";
import { HistoryController, historyStore, readHistoryList, readHistorySession } from "../src/history.js";
import { ProfileController } from "../src/profiles.js";
import { StoreHolder } from "../src/session.js";
import { ALERTS, DIGEST, HISTORY, OPENED, SESSION_KEPT, SESSION_PURGED, parentCore } from "./parentcore.js";
import { PROFILES } from "./profilecore.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");
const additions = JSON.parse(fs.readFileSync(path.join(ROOT, "contract-additions-m33a.json"), "utf8")) as { additions: { pointer: string; value: unknown }[] };
const defs = Object.fromEntries(additions.additions.filter((a) => a.pointer.startsWith("/$defs/")).map((a) => [a.pointer.slice("/$defs/".length), a.value]));
const STEP_STATUS = { enum: ["draft", "final", "awaiting", "checking", "correct", "incorrect", "equivalent_unsimplified", "unchecked"] };

/** Valid against the proposed definition (the board step status is the adopted events enum, inlined here). */
function proposed(name: string, value: unknown): boolean {
  const ajv = new Ajv2020({ strict: false, allErrors: true });
  ajv.addSchema({ $id: "https://jana.dev/contracts/api/events", $defs: { board_step_status: STEP_STATUS } });
  return ajv.validate({ $defs: defs, $ref: `#/$defs/${name}` }, value);
}

async function setup() {
  const fake = parentCore();
  const profiles = new ProfileController(fake.core.launch, new StoreHolder(), { fetch: fake.fetch });
  await profiles.load();
  await profiles.unlock(PROFILES[0]!.profile_id);
  return { ...fake, profiles, parents: new ParentController(profiles), history: new HistoryController(profiles) };
}

describe("contract-additions-m33a.json", () => {
  test("the local checks agree with the proposed definitions", () => {
    const cases: [string, unknown, (v: unknown) => unknown][] = [
      ["ParentDigest", DIGEST, readDigest], ["AlertList", { alerts: ALERTS }, readAlerts], ["HistoryList", HISTORY, readHistoryList],
      ["HistorySession", OPENED, (v) => readHistorySession(v, SESSION_KEPT)],
    ];
    const broken = (value: unknown, change: (v: Record<string, unknown>) => void) => { const copy = structuredClone(value) as Record<string, unknown>; change(copy); return copy; };
    for (const [name, good, read] of cases) {
      expect(proposed(name, good), name).toBe(true);
      expect(() => read(good)).not.toThrow();
      for (const bad of [broken(good, (v) => { v.extra = 1; }), broken(good, (v) => { Reflect.deleteProperty(v, Object.keys(v)[0] ?? ""); })]) {
        expect(proposed(name, bad), name).toBe(false);
        expect(() => read(bad), name).toThrow();
      }
    }
    // A free-text field the digest has no place for is refused, as the proposal refuses it (TCH-12: no free text).
    const withNote = { ...DIGEST, mastered: [{ ...DIGEST.mastered[0], note: "a note" }] };
    expect(proposed("ParentDigest", withNote)).toBe(false);
    expect(() => readDigest(withNote)).toThrow();
  });
});

describe("TCH-12, UXS-33", () => {
  test("test_tch12_digest_read_and_kept_per_profile", async () => {
    const s = await setup();
    await s.parents.loadDigest();
    expect(s.parents.getView()).toMatchObject({ digestStatus: "ready", digest: DIGEST });
    // Another student's summary is their own: nothing of the first one's carries over (JRN-13 F2).
    await s.profiles.unlock(PROFILES[1]!.profile_id);
    expect(s.parents.getView().digest).toBeNull();
    await s.parents.loadDigest();
    expect(s.parents.getView().digest).toMatchObject({ activity: "none", mastered: [], minutes_total: 0 });
  });

  test("test_tch12_digest_refused_or_unavailable", async () => {
    const s = await setup();
    s.setDigest({ ...DIGEST, paragraph: "This week Ada studied 99 hours." });
    await s.parents.loadDigest();
    expect(s.parents.getView().digestStatus).toBe("failed");
    s.setDigest(DIGEST);
    s.fail("/v1/digests");
    const fresh = new ParentController(s.profiles);
    await fresh.loadDigest();
    expect(fresh.getView().digestStatus).toBe("failed");
  });

  test("test_uxs33_conversation_starter_by_rule", () => {
    expect(conversationStarter(DIGEST)).toEqual({ kind: "watch", topic: "Inside the atom" });
    expect(conversationStarter({ ...DIGEST, to_watch: [] })).toEqual({ kind: "secured", topic: "Motion" });
    expect(conversationStarter({ ...DIGEST, to_watch: [], mastered: [] })).toEqual({ kind: "studied", topic: null });
    expect(conversationStarter({ ...DIGEST, to_watch: [], mastered: [], activity: "none" })).toEqual({ kind: "start", topic: null });
  });
});

describe("TCH-14", () => {
  test("test_tch14_alerts_listed_and_put_away", async () => {
    const s = await setup();
    await s.parents.loadAlerts();
    expect(s.parents.getView().alerts.map((a) => a.kind)).toEqual(["mastery_drop", "wellbeing_message_shown", "mock_result"]);
    expect(await s.parents.dismiss(ALERTS[0]!.alert_id)).toBe(true);
    expect(s.parents.getView().alerts).toHaveLength(2);
    const sent = s.requests.find((r) => r.method === "POST");
    expect(sent).toMatchObject({ path: `/v1/alerts/${ALERTS[0]!.alert_id}/dismiss`, body: {} });
    expect(sent?.key).toMatch(/^cli_/);
    // Already gone at the core: it leaves the list too.
    expect(await s.parents.dismiss(ALERTS[0]!.alert_id)).toBe(true);
    s.fail("/v1/alerts");
    expect(await s.parents.dismiss(ALERTS[1]!.alert_id)).toBe(false);
    expect(s.parents.getView()).toMatchObject({ dismissFailed: true, dismissing: null });
  });
});

describe("UXS-48", () => {
  test("test_uxs48_history_listed_and_opened_read_only", async () => {
    const s = await setup();
    await s.history.load();
    expect(s.history.getView()).toMatchObject({ status: "ready", retentionDays: 90 });
    expect(s.history.getView().sessions.map((e) => e.transcript)).toEqual(["kept", "purged"]);
    await s.history.open(SESSION_KEPT);
    const opened = s.history.getView().opened;
    expect(opened?.status).toBe("ready");
    const store = historyStore(opened!.session!);
    const session = store.sessions[SESSION_KEPT]!;
    expect(session.turn_ids).toHaveLength(1);
    expect(Object.values(store.messages).map((m) => m.content)).toEqual([[{ type: "text", text: OPENED.messages[0]!.role === "student" ? OPENED.messages[0]!.text : "" }]]);
    expect(Object.values(store.parts)[0]).toMatchObject({ kind: "text", status: "complete" });
    expect(Object.values(store.boards)[0]?.step_ids).toEqual([OPENED.boards[0]!.steps[0]!.step_id]);
    expect(Object.values(store.requests)).toEqual([]); // nothing to answer: read-only
    // A purged session opens with nothing in it.
    await s.history.open(SESSION_PURGED);
    const purged = s.history.getView().opened?.session;
    expect(purged?.messages).toEqual([]);
    expect(historyStore(purged!).sessions[SESSION_PURGED]?.turn_ids).toEqual([]);
    // Only GETs: history sends nothing anywhere.
    expect(s.requests.every((r) => r.method === "GET")).toBe(true);
  });

  test("test_uxs48_history_dropped_with_the_profile", async () => {
    const s = await setup();
    await s.history.load();
    await s.history.open(SESSION_KEPT);
    await s.profiles.unlock(PROFILES[1]!.profile_id);
    expect(s.history.getView()).toMatchObject({ status: "idle", sessions: [], opened: null });
    await s.history.load();
    expect(s.history.getView().sessions).toEqual([]);
    await s.history.open(SESSION_KEPT);
    expect(s.history.getView().opened?.status).toBe("failed");
  });
});
