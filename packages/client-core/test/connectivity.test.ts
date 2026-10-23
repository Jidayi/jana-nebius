// UIA-23, UXS-06 and UXS-08 (client half): the connectivity slice folds `connectivity.status`, `egress.notice` and the
// cloud fallback notices, and derives the indicator state of TABLE UXS-06a with its TABLE DSN-19a alias. The named
// acceptance tests are in packages/ui/test/connectivity.test.tsx; these cover the pure functions underneath.
import { describe, expect, test } from "vitest";
import {
  CLOUD_FALLBACK_NOTICES, INDICATOR_ALIAS, INDICATOR_STATES, ONLINE_FEATURES, activeEgress, cloudAnswered, emptyConnectivity,
  indicatorOf, queuedItems, reduceConnectivity, seedConnectivity, turnEgress, type ConnectivityReply, type ConnectivitySlice,
} from "../src/connectivity.js";
import { ProfileController } from "../src/profiles.js";
import type { Envelope } from "../src/queue.js";
import { StoreHolder } from "../src/session.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const SESSION = `ses_${"0".repeat(26)}`;
const TURN = `trn_${"1".repeat(26)}`;
let seq = 0;

function app(event: Record<string, unknown> & { type: string }): Envelope {
  seq += 1;
  return { v: 1, channel: "app", seq, epoch: "ep_app", session_id: null, turn_id: null, ts: 1_000 + seq, event };
}

function session(event: Record<string, unknown> & { type: string }, turnId: string | null = TURN): Envelope {
  seq += 1;
  return { v: 1, channel: "session", seq, epoch: "ep_session", session_id: SESSION, turn_id: turnId, ts: 1_000 + seq, event };
}

const egress = (feature: string, state: "started" | "ended" | "blocked", destination = "Cloud tutor") =>
  ({ type: "egress.notice", feature, state, destination_label: destination, data_classes: ["question_text"] });

function seeded(network: ConnectivityReply["network"], on: string[] = [], queued: Record<string, number> = {}): ConnectivitySlice {
  const features: ConnectivityReply["features"] = {};
  for (const f of ["cloud_tier", "downloads", "update_checks", "telemetry", "crash_reports"]) {
    features[f] = { enabled: on.includes(f), state: "idle", queued_items: queued[f] ?? 0, last_sent_at: null };
  }
  return seedConnectivity(emptyConnectivity(), { network, features });
}

describe("connectivity slice", () => {
  test("lists only the features the core lists, in the order of TABLE ARC-07a, and ignores unknown ids", () => {
    const slice = seedConnectivity(emptyConnectivity(), {
      network: "online",
      features: { telemetry: { enabled: true, state: "idle" }, cloud_tier: { enabled: false, state: "idle" }, hover_boards: { enabled: true, state: "idle" } },
    });
    expect(slice.features.map((f) => f.feature)).toEqual(["cloud_tier", "telemetry"]);
    expect(slice.features[1]).toEqual({ feature: "telemetry", enabled: true, state: "idle", queued_items: 0, last_sent_at: null });
    expect(ONLINE_FEATURES).toEqual(["cloud_tier", "downloads", "update_checks", "cloud_backup", "multi_device", "parent_remote_view", "cloud_voice", "study_materials", "telemetry", "crash_reports"]);
  });

  test("connectivity.status replaces network and features but keeps what was last sent", () => {
    let slice = seedConnectivity(emptyConnectivity(), { network: "offline", features: { telemetry: { enabled: true, state: "queued", queued_items: 2, last_sent_at: "2026-10-01T09:00:00Z" } } });
    slice = reduceConnectivity(slice, app({ type: "connectivity.status", network: "online", checked_ts: 5, features: [{ feature: "telemetry", enabled: true, state: "idle", queued_items: 0 }] }));
    expect(slice.network).toBe("online");
    expect(slice.checked_ts).toBe(5);
    expect(slice.features).toEqual([{ feature: "telemetry", enabled: true, state: "idle", queued_items: 0, last_sent_at: "2026-10-01T09:00:00Z" }]);
  });

  test("the indicator follows TABLE UXS-06a with the aliases of TABLE DSN-19a", () => {
    expect(indicatorOf(seeded("off")).state).toBe("all-off");
    expect(indicatorOf(seeded("online")).state).toBe("all-off"); // nothing on: everything stays here
    expect(indicatorOf(seeded("offline", ["telemetry"])).state).toBe("offline");
    expect(indicatorOf(seeded("unknown", ["telemetry"])).state).toBe("offline");
    expect(indicatorOf(seeded("limited", ["telemetry"])).state).toBe("limited");
    expect(indicatorOf(seeded("metered", ["telemetry"])).state).toBe("metered");
    expect(indicatorOf(seeded("online", ["telemetry", "update_checks"]))).toMatchObject({ state: "online-idle", enabled: ["update_checks", "telemetry"] });
    const sending = reduceConnectivity(seeded("online", ["telemetry"]), app(egress("telemetry", "started", "Usage reports")));
    expect(indicatorOf(sending)).toMatchObject({ state: "sending", icon: "up-arrow", alias: "connectivity-egress" });
    const cloud = reduceConnectivity(seeded("online", ["cloud_tier"]), session(egress("cloud_tier", "started")));
    expect(indicatorOf(cloud)).toMatchObject({ state: "cloud-tutor", icon: "cloud", alias: "connectivity-online" });
    expect(indicatorOf(cloud).egress?.destination_label).toBe("Cloud tutor");
    const unavailable = seedConnectivity(emptyConnectivity(), { network: "online", features: { cloud_tier: { enabled: true, state: "unavailable" } } });
    expect(indicatorOf(unavailable)).toMatchObject({ state: "online-unavailable", icon: "cloud-off", alias: "connectivity-offline" });
    expect(INDICATOR_STATES).toEqual(["all-off", "offline", "limited", "metered", "online-idle", "sending", "cloud-tutor", "online-unavailable"]);
    expect(INDICATOR_ALIAS).toEqual({
      "all-off": "connectivity-local", offline: "connectivity-offline", limited: "connectivity-offline", metered: "connectivity-online",
      "online-idle": "connectivity-online", sending: "connectivity-egress", "cloud-tutor": "connectivity-online", "online-unavailable": "connectivity-offline",
    });
  });

  test("egress in flight is always shown, whatever the network state, and ended or blocked clears it", () => {
    for (const network of ["off", "offline", "limited", "metered", "online", "unknown"] as const) {
      let slice = seeded(network, ["telemetry"]);
      slice = reduceConnectivity(slice, app(egress("crash_reports", "started", "Crash reports")));
      expect(indicatorOf(slice).state, network).toBe("sending");
      slice = reduceConnectivity(slice, app(egress("crash_reports", "ended", "Crash reports")));
      expect(activeEgress(slice)).toEqual([]);
      slice = reduceConnectivity(slice, app(egress("crash_reports", "blocked", "Crash reports")));
      expect(indicatorOf(slice).state, network).not.toBe("sending");
    }
  });

  test("a turn is answered by the cloud only when its cloud egress started and no fallback notice followed", () => {
    let slice = seeded("online", ["cloud_tier"]);
    slice = reduceConnectivity(slice, session({ type: "turn.start", turn_id: TURN, user_message_id: null, client_message_id: null, intent: "ask", mode: "guided", fork: false }));
    slice = reduceConnectivity(slice, session(egress("cloud_tier", "started")));
    expect(turnEgress(slice, TURN)?.state).toBe("started");
    slice = reduceConnectivity(slice, session(egress("cloud_tier", "ended")));
    expect(cloudAnswered(turnEgress(slice, TURN))).toBe(true);
    for (const code of CLOUD_FALLBACK_NOTICES) {
      const fallen = reduceConnectivity(slice, session({ type: "notice", notice_id: `ntc_${code}`, level: "info", code, message_key: `notice.${code}`, params: {}, action: null }));
      expect(cloudAnswered(turnEgress(fallen, TURN)), code).toBe(false);
      expect(indicatorOf(fallen).state).toBe("online-unavailable");
    }
    // The turn ends with a cloud request still marked in flight (a dropped `ended`): it is no longer shown as sending.
    let dropped = reduceConnectivity(seeded("online", ["cloud_tier"]), session(egress("cloud_tier", "started"), "trn_X"));
    dropped = reduceConnectivity(dropped, session({ type: "turn.end", status: "complete" }, "trn_X"));
    expect(activeEgress(dropped)).toEqual([]);
  });

  test("an envelope at or below what was seen changes nothing", () => {
    const started = session(egress("cloud_tier", "started"));
    const ended = session(egress("cloud_tier", "ended"));
    let slice = reduceConnectivity(reduceConnectivity(seeded("online", ["cloud_tier"]), started), ended);
    const again = reduceConnectivity(slice, started);
    expect(again).toBe(slice);
    slice = again;
    expect(activeEgress(slice)).toEqual([]);
  });

  test("queued items are counted across the listed features", () => {
    expect(queuedItems(seeded("offline", ["telemetry", "crash_reports"], { telemetry: 2, crash_reports: 1 }))).toBe(3);
  });

  test("the controller is part of the profile controller, fed by the session store, and cleared with the profile", async () => {
    const core = new FakeProfileCore();
    core.features.cloud_tier = true;
    core.network = "online";
    const holder = new StoreHolder();
    const profiles = new ProfileController(core.launch, holder, { fetch: core.fetch });
    await profiles.load();
    await profiles.unlock(PROFILES[0]!.profile_id);
    await profiles.connectivity.load();
    expect(indicatorOf(profiles.connectivity.getView()).state).toBe("online-idle");
    holder.deliver([session(egress("cloud_tier", "started"))]);
    expect(indicatorOf(profiles.connectivity.getView()).state).toBe("cloud-tutor");
    await profiles.lock();
    expect(activeEgress(profiles.connectivity.getView())).toEqual([]);
    expect(profiles.connectivity.getView().network).toBe("online"); // device-wide state stays
  });
});
