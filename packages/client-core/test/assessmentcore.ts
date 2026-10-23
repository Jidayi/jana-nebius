import { errors } from "@jana/contracts-ts";
import type { Assessment, AssessmentStart } from "../src/assessments.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

export const ASSESSMENT_ID = "00000000000000000000000090";
export function assessment(kind: AssessmentStart["kind"] = "diagnostic", count = 0, subject: AssessmentStart["subject"] = "physics"): Assessment {
  const code = { mathematics: "mth", physics: "phy", chemistry: "chm", biology: "bio", accounting: "acc" }[subject];
  const kc = `kc.${code}.o.synthetic`;
  const marks = kind === "diagnostic" ? {} : { marks: 1 };
  return { assessment_id: ASSESSMENT_ID, kind, subject, kc_id: kind === "diagnostic" ? null : kc, state: "in_progress", answered_count: count,
    current_item: { item_id: `itm.${code}.o.synthetic.000${count + 1}`, pack_id: `pack.${code}.o`, pack_version: "1.0.0", kc_ids: [kc], kind: "mcq",
      stem: `Synthetic question ${count + 1}`, parts: [{ part_id: "a", prompt: "Choose one", uses_parts: [], input: { kind: "mcq", options: [{ id: "a", label: "First option" }, { id: "b", label: "Second option" }] }, ...marks }], visual: null, ...marks },
    available_at: null, retry_at: null, outcome_topics: [{ topic_id: `cur.${code}.o.synthetic`, status: "learning" }],
    answered_items: Array.from({ length: count }, (_, n) => ({ item_id: `itm.${code}.o.synthetic.000${n + 1}`, attempt_id: `attempt${n}`, answered_at: "2026-10-17T10:00:00Z" })) };
}
export function assessmentCore() {
  const core = new FakeProfileCore();
  const rows = new Map<string, Assessment[]>();
  const writes: { path: string; body: Record<string, unknown>; key: string | null }[] = [];
  const cached = new Map<string, Assessment>();
  let lose = false, failure: string | null = null;
  const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
  const fetch = (async (input, init = {}) => {
    const path = new URL(String(input)).pathname;
    if (!path.startsWith("/v1/assessments")) return core.fetch(input, init);
    const headers = new Headers(init.headers), profile = PROFILES.find((p) => core.tokenOf(p.profile_id) === headers.get("x-profile-token"))?.profile_id;
    if (profile === undefined) return json({ error: { code: "profile_token_expired", retryable: false } }, 401);
    const list = rows.get(profile) ?? []; rows.set(profile, list);
    if (init.method === undefined || init.method === "GET") return json(path === "/v1/assessments" ? list : list.find((a) => a.assessment_id === path.split("/")[3]));
    const body = JSON.parse(String(init.body)) as Record<string, unknown>, key = headers.get("idempotency-key");
    writes.push({ path, body, key });
    if (failure !== null) return json({ error: { code: failure, retryable: false } }, 423);
    let current = cached.get(key ?? "");
    if (current === undefined) {
      if (path === "/v1/assessments") {
        if (errors("learning/student-records#/$defs/AssessmentStart", body).length) throw new Error("invalid start fixture");
        current = assessment(body.kind as AssessmentStart["kind"], 0, body.subject as AssessmentStart["subject"]); list.unshift(current);
      } else {
        const previous = list.find((a) => a.assessment_id === path.split("/")[3]);
        if (previous === undefined) return json({ error: { code: "not_found", retryable: false } }, 404);
        if (path.endsWith("/answers")) {
          if (errors("learning/student-records#/$defs/AssessmentAnswer", body).length) throw new Error("invalid answer fixture");
          current = assessment(previous.kind, previous.answered_count + 1, previous.subject);
          if (current.answered_count === 2) current = { ...current, state: previous.kind === "diagnostic" ? "completed" : "waiting", current_item: null, available_at: previous.kind === "diagnostic" ? null : "2026-10-20T10:00:00Z" };
          if (previous.kind === "mastery_check" && current.answered_count === 3) current = { ...current, state: "completed", current_item: null, outcome_topics: previous.outcome_topics.map((t) => ({ ...t, status: "mastered" })) };
          if (previous.kind === "mastery_check") current.last_mark = { verdict: "correct", marks_awarded: 1, marks_total: 1 };
        } else current = { ...previous, state: path.endsWith("/stop") ? "stopped" : "in_progress" };
        list.splice(list.indexOf(previous), 1, current);
      }
      cached.set(key ?? "", structuredClone(current));
    }
    if (lose) throw new Error("synthetic lost response");
    return json(current);
  }) as typeof globalThis.fetch;
  return { core, fetch, rows, writes, lose: (value: boolean) => { lose = value; }, fail: (code: string | null) => { failure = code; } };
}
