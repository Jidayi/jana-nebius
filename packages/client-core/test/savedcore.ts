import type { SavedQuestion } from "../src/saved-questions.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";
export const SAVED: SavedQuestion = {
  question_id: "00000000000000000000000090", session_id: "ses_00000000000000000000000001", status: "kept", expires_at: "2027-01-17T00:00:00Z",
  snapshot: { kind: "saved_question", question_id: "00000000000000000000000090", subject: "physics", topic_id: "cur.phy.o.motion", problem: "Find the speed of a synthetic cyclist.", board: [{ latex: "v=20/4", reason: "Divide distance by time" }], reason: "student_requested", created_at: "2026-10-17T00:00:00Z" },
};
export function savedCore() {
  const core = new FakeProfileCore(), questions = new Map<string, SavedQuestion[]>(), requests: { path: string; method: string; key: string | null; body: unknown }[] = [], cache = new Map<string, unknown>();
  let lose = false;
  const fetcher = (async (input, init = {}) => {
    const path = new URL(String(input)).pathname;
    if (!path.startsWith("/v1/saved-questions")) return core.fetch(input, init);
    const headers = new Headers(init.headers), profile = PROFILES.find((p) => core.tokenOf(p.profile_id) === headers.get("x-profile-token"))?.profile_id ?? "missing";
    let rows = questions.get(profile) ?? []; questions.set(profile, rows);
    if (!init.method || init.method === "GET") return new Response(JSON.stringify(rows));
    const key = headers.get("idempotency-key"), body = init.body ? JSON.parse(String(init.body)) : null;
    requests.push({ path, method: init.method, key, body });
    let result = cache.get(key ?? "");
    if (!cache.has(key ?? "")) {
      if (init.method === "POST") { result = structuredClone(SAVED); rows.push(result as SavedQuestion); }
      if (init.method === "PATCH") { result = { ...rows[0], status: body.status }; rows = [result as SavedQuestion]; questions.set(profile, rows); }
      if (init.method === "DELETE") { questions.set(profile, []); result = null; }
      cache.set(key ?? "", result);
    }
    if (lose) throw new Error("synthetic lost response");
    return init.method === "DELETE" ? new Response(null, { status: 204 }) : new Response(JSON.stringify(result));
  }) as typeof fetch;
  return { core, questions, fetch: fetcher, requests, lose: (value: boolean) => { lose = value; } };
}
