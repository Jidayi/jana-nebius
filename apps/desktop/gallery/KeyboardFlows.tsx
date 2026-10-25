// Synthetic keyboard-journey core. Only this development/benchmark entry imports the fixture provider.
import { useMemo } from "react";
import { type CapturedQuestion, type SubjectMap } from "@jana/client-core";
import { STATES } from "@jana/ui/gallery";
import { FakeProfileCore } from "../../../packages/client-core/test/profilecore.js";
import { App, createRuntime } from "../src/App.js";

const payload = <T,>(id: string): T => { const state = STATES.find((s) => s.id === id); if (!state) throw new Error(`Missing keyboard fixture ${id}`); return structuredClone(state.payload) as T; };
const option = (n: number) => ({
  item_id: `itm.phy.o.motion.08${n}0`, pack_id: "pack.phy.o", pack_version: "1.0.1", kc_ids: [`kc.phy.o.motion.synthetic_${n}`], kind: "mcq", stem: `Synthetic question ${n}.`,
  parts: [{ part_id: "a", prompt: `Synthetic question ${n}.`, marks: 1, uses_parts: [], input: { kind: "mcq", options: [{ id: "x", label: `Right ${n}` }, { id: "y", label: `Other ${n}` }] } }],
  visual: null, marks: 1,
});

export function KeyboardFlows() {
  const { runtime, evidence } = useMemo(() => {
    const core = new FakeProfileCore();
    const map = payload<{ map: SubjectMap }>("subject-map.canonical.topic-sheet").map;
    const lesson = payload<{ lesson: Record<string, unknown> & { lesson_id: string } }>("lesson-player.canonical").lesson;
    core.maps.set(map.subject_id, map); core.lessons.set(lesson.lesson_id, lesson);
    core.packs.push({ pack_id: "pack.phy.o", subject: "phy", level: "O", version: "1.0.1", signature_ok: true, size_bytes: 1 });
    const questions = [option(1), option(2), option(3)];
    core.practiceItems = questions;
    core.mark = () => ({ verdict: "incorrect", category: "other" });
    core.mockPapers = [{ paper_id: "mck.phy.o.0001", subject: "physics", level: "O", title: "Keyboard synthetic mock", paper_kind: "paper_1_objective", duration_minutes: 60, total_marks: 3, questions: 3, calculator: true }];
    core.mockQuestions = questions;
    core.mockRight = (_q, answer) => (answer as { parts: { option_id: string }[] }).parts[0]?.option_id === "x";
    const base = payload<CapturedQuestion>("photo-capture.canonical.awaiting-confirmation");
    let capture = base;
    const fetch: typeof globalThis.fetch = async (input, init = {}) => {
      const path = new URL(String(input)).pathname;
      if (/^\/v1\/captures(?:\/|$)/.test(path)) {
        const method = init.method ?? "GET";
        const body = init.body instanceof FormData ? JSON.parse(String(init.body.get("meta"))) as Record<string, unknown> : typeof init.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : {};
        core.log.push({ method, path, headers: {}, body });
        if (path === "/v1/captures") capture = { ...base, session_id: String(body.session_id), status: "drafting", text: "", regions: [], attachments: [] };
        else if (path.endsWith("/read")) capture = { ...base, session_id: capture.session_id ?? null, attachments: [] };
        else if (path.endsWith("/confirm")) capture = { ...capture, text: String(body.text), status: "confirmed", confirmation: { confirmed: true, method: "accepted", confirmed_at: Date.now(), edit_distance: 0 } };
        if (method === "DELETE") return new Response(null, { status: 204 });
        return Response.json(capture);
      }
      if (path.endsWith("/captures")) return Response.json({ captures: [] });
      return core.fetch(input, init);
    };
    // Read-only evidence for the browser runner; no script can drive the app through this object.
    return { runtime: createRuntime(core.launch, fetch), evidence: () => ({ log: core.log, helped: core.helped, reviewed: core.reviewed, lessonId: lesson.lesson_id, lessonKcs: lesson.kc_ids, journeys: [...core.journeys.values()] }) };
  }, []);
  Object.defineProperty(globalThis, "__jana_keyboard_evidence", { configurable: true, get: evidence });
  return <App runtime={runtime} />;
}
