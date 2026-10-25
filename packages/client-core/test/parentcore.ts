// A fake core for the parent views and session history (TCH-12, TCH-14, UXS-33, UXS-48): the digest, the alerts with
// their dismiss, and one profile's history, each refused without that profile's token as the real core refuses it.
// Every learner, number and line here is synthetic.
import type { AlertView, ParentDigest } from "../src/parents.js";
import type { HistoryList, HistorySession } from "../src/history.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const id = (n: number) => n.toString().padStart(26, "0");

export const DIGEST: ParentDigest = {
  week_start: "2026-10-19", week_end: "2026-10-25", generated_at: 1_792_951_200_000, final: false, activity: "enough",
  time_by_day: ["19", "20", "21", "22", "23", "24", "25"].map((d, i) => ({ day: `2026-10-${d}`, minutes: [25, 0, 40, 0, 50, 20, 0][i]! })),
  minutes_total: 135, days_studied: 4, sessions: 5,
  mastered: [{ kc_id: "kc.phy.o.motion.average_speed", subject: "physics", topic_id: "cur.phy.o.motion", topic_title: "Motion", statement: "Calculate average speed" }],
  to_watch: [{ kc_id: "kc.phy.o.atom.isotopes", subject: "physics", topic_id: "cur.phy.o.atom", topic_title: "Inside the atom", statement: "Explain isotopes", reason: "learning_long" }],
  mocks: [{ exam_id: `exm_${id(7)}`, paper_id: "mck.phy.o.0001", submitted_at: 1_792_836_000_000, title: "Physics Paper 2", marks_awarded: 31, marks_available: 50 }],
  solutions_viewed: 2, bottom_out_hints: 1, steps: 12, steps_with_hints: 4, streak_days: 3, exam: { subject: "physics", days: 219 },
};

export const ALERTS: AlertView[] = [
  { alert_id: `alr_${id(3)}`, kind: "mastery_drop", severity: "info", created_at: 1_792_936_000_000, kc_id: "kc.phy.o.motion.average_speed" },
  { alert_id: `alr_${id(2)}`, kind: "wellbeing_message_shown", severity: "urgent", created_at: 1_792_836_000_000, kc_id: null },
  { alert_id: `alr_${id(1)}`, kind: "mock_result", severity: "info", created_at: 1_792_736_000_000, kc_id: null },
];

export const SESSION_KEPT = `ses_${id(9)}`;
export const SESSION_PURGED = `ses_${id(4)}`;

export const HISTORY: HistoryList = {
  sessions: [
    { session_id: SESSION_KEPT, mode: "guided", subject: "physics", topic_id: "cur.phy.o.motion", topic_title: "Motion", title: "Speed of a cyclist", started_at: 1_792_926_000_000, duration_ms: 1_500_000, transcript: "kept" },
    { session_id: SESSION_PURGED, mode: "practice", subject: "physics", topic_id: null, topic_title: null, title: "", started_at: 1_788_000_000_000, duration_ms: null, transcript: "purged" },
  ],
  next_before: null, retention_days: 90,
};

export const OPENED: HistorySession = {
  session: HISTORY.sessions[0]!,
  messages: [
    { role: "student", turn_id: `msg_${id(10)}`, text: "A synthetic cyclist rides 20 m in 4 s. How fast?" },
    { role: "tutor", turn_id: `trn_${id(11)}`, part_ids: [`prt_${id(12)}`] },
  ],
  parts: { [`prt_${id(12)}`]: { part_id: `prt_${id(12)}`, turn_id: `trn_${id(11)}`, kind: "text", index: 0, status: "complete", text: "Speed is distance over time." } },
  boards: [{ board_id: `brd_${id(13)}`, part_id: null, steps: [{ step_id: `stp_${id(14)}`, index: 0, latex: "v=\\frac{20}{4}", reason: "Divide distance by time", owner: "tutor", status: "final" }] }],
};

export function parentCore() {
  const core = new FakeProfileCore();
  const alerts = new Map<string, AlertView[]>([[PROFILES[0]!.profile_id, structuredClone(ALERTS)]]);
  const requests: { method: string; path: string; key: string | null; body: unknown }[] = [];
  let digest: unknown = DIGEST;
  let failing: string | null = null;
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  const error = (code: string, status: number) => json({ error: { code, message: code, retryable: false } }, status);
  const fetcher = (async (input, init = {}) => {
    const url = new URL(String(input));
    const path = url.pathname;
    if (!/^\/v1\/(digests|alerts|history)/.test(path)) return core.fetch(input, init);
    const headers = new Headers(init.headers);
    const profile = PROFILES.find((p) => core.tokenOf(p.profile_id) === headers.get("x-profile-token"))?.profile_id;
    requests.push({ method: init.method ?? "GET", path: path + url.search, key: headers.get("idempotency-key"), body: init.body ? JSON.parse(String(init.body)) : null });
    if (profile === undefined) return error("profile_token_expired", 401);
    if (failing !== null && path.startsWith(failing)) return error("internal_error", 500);
    const own = profile === PROFILES[0]!.profile_id;
    if (path === "/v1/digests/latest") return json(own ? digest : { ...DIGEST, activity: "none", minutes_total: 0, days_studied: 0, sessions: 0, mastered: [], to_watch: [], mocks: [], time_by_day: DIGEST.time_by_day.map((d) => ({ ...d, minutes: 0 })) });
    if (path === "/v1/alerts") return json({ alerts: alerts.get(profile) ?? [] });
    const dismiss = /^\/v1\/alerts\/([^/]+)\/dismiss$/.exec(path);
    if (dismiss !== null) {
      const rows = alerts.get(profile) ?? [];
      if (!rows.some((a) => a.alert_id === dismiss[1])) return error("not_found", 404);
      alerts.set(profile, rows.filter((a) => a.alert_id !== dismiss[1]));
      return new Response(null, { status: 204 });
    }
    if (path === "/v1/history") return json(own ? HISTORY : { sessions: [], next_before: null, retention_days: 90 });
    const one = /^\/v1\/history\/([^/]+)$/.exec(path);
    if (one !== null && own && one[1] === SESSION_KEPT) return json(OPENED);
    if (one !== null && own && one[1] === SESSION_PURGED) return json({ session: HISTORY.sessions[1], messages: [], parts: {}, boards: [] });
    return error("not_found", 404);
  }) as typeof fetch;
  return {
    core, fetch: fetcher, requests,
    setDigest: (value: unknown) => { digest = value; },
    fail: (prefix: string | null) => { failing = prefix; },
  };
}
