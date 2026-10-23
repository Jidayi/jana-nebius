import { readSessionNote, type SessionNote } from "../src/session-notes.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";
export const NOTE: SessionNote = { note_id: "snt_00000000000000000000000090", session_id: PROFILES[0]!.session_id, kind: "session", title: "Speed", subject: "physics", kc_ids: ["kc.phy.o.motion.average_speed"],
  statements: [{ section: "method", text: "Divide distance by time.", reference: { session_id: PROFILES[0]!.session_id, turn_id: "trn_00000000000000000000000001", trace_id: null } }],
  state: "ready", private: false, source_revision: 1, withheld: 0, created_at: 1792224000000, updated_at: 1792224000000 };
export function notesCore() {
  const core = new FakeProfileCore(), rows = new Map<string, SessionNote[]>([[PROFILES[0]!.profile_id, [structuredClone(NOTE)]]]);
  const requests: { method: string; path: string; body: unknown }[] = [];
  const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });
  const fetcher = (async (input, init = {}) => {
    const url = new URL(String(input)), headers = new Headers(init.headers);
    if (!url.pathname.startsWith("/v1/session-notes") && !url.pathname.endsWith("/end")) return core.fetch(input, init);
    const profile = PROFILES.find((p) => core.tokenOf(p.profile_id) === headers.get("x-profile-token"))?.profile_id ?? "missing";
    let notes = rows.get(profile) ?? []; rows.set(profile, notes);
    if (!init.method || init.method === "GET") return json(notes.map((n) => readSessionNote(n)).filter((n) => !url.searchParams.get("q") || !n.private && JSON.stringify(n).toLowerCase().includes(url.searchParams.get("q")!.toLowerCase())));
    const body = init.body ? JSON.parse(String(init.body)) : {};
    requests.push({ method: init.method, path: url.pathname, body });
    if (url.pathname.endsWith("/end")) return json({ session_id: NOTE.session_id, state: "ended" });
    const id = url.pathname.split("/")[3], note = notes.find((n) => n.note_id === id);
    if (!note) return json({ error: { code: "not_found", retryable: false } }, 404);
    if (url.pathname.endsWith("/open")) return note.private && !body.confirm ? json({ error: { code: "validation_failed", retryable: false } }, 422) : json(note);
    if (init.method === "PATCH") { note.private = body.private; return json(readSessionNote(note)); }
    if (init.method === "DELETE") { notes = notes.filter((n) => n !== note); rows.set(profile, notes); return new Response(null, { status: 204 }); }
    return json(note);
  }) as typeof fetch;
  return { core, fetch: fetcher, rows, requests };
}
