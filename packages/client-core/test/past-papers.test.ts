// ASM-27 and LRN-44 from the client's side: a past paper imported from pasted text and from a private study source
// (with the study area's open grant), a refused import kept as its reason, and exam dates with the countdown and a
// reminder put away. Over the fake profile core, with the two new routes answered here; synthetic content only.
import { describe, expect, test } from "vitest";
import { ExamDateController, PastPaperController, ProfileController, StoreHolder } from "../src/index.js";
import { FakeProfileCore, PROFILES } from "./profilecore.js";

const ULID = "0".repeat(26);
const SUMMARY = {
  paper_id: `ppr_${ULID}`, title: "Physics paper 2 (practice)", subject: "physics", duration_minutes: 60, total_marks: 6, questions: 3,
  has_mark_scheme: true, syllabus: "cur.phy.o", linked: true, calculator: true, imported_ts: 1, marking: { checked: 2, key: 1, judged: 1 },
};
const VIEW = { ...SUMMARY, questions_found: [{ question_id: "q1", number_label: "1", marks: 2, marking: "checked", topic_ids: ["cur.phy.o.motion"] }] };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

async function opened(answer: (method: string, path: string, body: unknown, headers: Headers) => Response | null) {
  const core = new FakeProfileCore(() => 1_800_000_000_000);
  const fetch = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    const body = typeof init.body === "string" ? JSON.parse(init.body) as unknown : null;
    const reply = url.pathname.startsWith("/v1/past-papers") || url.pathname.startsWith("/v1/exam-dates") || url.pathname.startsWith("/v1/study/")
      ? answer(method, url.pathname, body, new Headers(init.headers)) : null;
    return reply ?? core.fetch(input, init);
  };
  const profiles = new ProfileController(core.launch, new StoreHolder(), { fetch });
  await profiles.load();
  expect(await profiles.unlock(PROFILES[0]!.profile_id)).toBe(true);
  return profiles;
}

describe("ASM-27", () => {
  test("pasted text becomes a study source, then an imported paper that says how it will be marked", async () => {
    const asked: { method: string; path: string; body: unknown; grant: string | null }[] = [];
    let papers: unknown[] = [];
    const profiles = await opened((method, path, body, headers) => {
      asked.push({ method, path, body, grant: headers.get("x-study-open") });
      if (path === "/v1/past-papers" && method === "GET") return json({ papers });
      if (path === "/v1/study/workspace") return json({ sources: { items: [{ source_id: `src_${"7".repeat(26)}`, revision: 2, kind: "pdf", private: true, created_at: "x", updated_at: "x" }], next_cursor: null }, jobs: [] });
      if (path === "/v1/study/sources" && method === "POST") return json({ source_id: `src_${"1".repeat(26)}`, revision: 1 });
      if (path.endsWith("/open")) return json({ open_token: "grant-1", source: {}, expires_at: "x" });
      if (path === "/v1/past-papers" && method === "POST") { papers = [SUMMARY]; return json(VIEW); }
      return null;
    });
    const controller = new PastPaperController(profiles);
    await controller.load();
    expect(controller.getView()).toMatchObject({ status: "ready", papers: [], sources: [{ sourceId: `src_${"7".repeat(26)}`, title: null, private: true }] });
    const ok = await controller.importPaper({ title: "Physics paper 2 (practice)", subject: "physics", minutes: 60, paper: { text: "1 Calculate ... [2]" }, scheme: { sourceId: `src_${"7".repeat(26)}` } });
    expect(ok).toBe(true);
    const sent = asked.find((a) => a.method === "POST" && a.path === "/v1/past-papers")!;
    expect(sent.body).toMatchObject({ subject: "physics", duration_minutes: 60, paper: { source_id: `src_${"1".repeat(26)}`, revision: 1 }, mark_scheme: { source_id: `src_${"7".repeat(26)}`, revision: 2 } });
    expect(sent.grant).toBe("grant-1"); // the private mark scheme is read with the study area's own grant
    expect(controller.getView()).toMatchObject({ importing: false, imported: { paper_id: SUMMARY.paper_id }, papers: [SUMMARY] });
  });

  test("a refused import keeps its reason and imports nothing", async () => {
    const profiles = await opened((method, path) => {
      if (path === "/v1/past-papers" && method === "GET") return json({ papers: [] });
      if (path === "/v1/study/workspace") return json({ sources: { items: [], next_cursor: null }, jobs: [] });
      if (path === "/v1/study/sources") return json({ source_id: `src_${"1".repeat(26)}`, revision: 1 });
      if (path === "/v1/past-papers") return json({ error: { code: "validation_failed", retryable: false, details: { reason: "no_questions_found" } } }, 422);
      return null;
    });
    const controller = new PastPaperController(profiles);
    await controller.load();
    expect(await controller.importPaper({ title: "Notes", subject: "physics", minutes: 30, paper: { text: "no questions" }, scheme: null })).toBe(false);
    expect(controller.getView()).toMatchObject({ refused: "no_questions_found", imported: null, importing: false });
  });
});

describe("LRN-44", () => {
  test("exam dates: added, counted down to, and a reminder put away on this device", async () => {
    const exam = { exam_id: `exd_${ULID}`, subject: "physics", name: "Physics paper 2", date: "2027-05-20", time: "09:00", reminders: true };
    let dismissed = false;
    const asked: { method: string; path: string; body: unknown }[] = [];
    const profiles = await opened((method, path, body) => {
      asked.push({ method, path, body });
      if (path === "/v1/exam-dates" && method === "GET") {
        return json({ exams: [exam], countdown: { exam_id: exam.exam_id, subject: "physics", name: exam.name, date: exam.date, time: exam.time, days: 7 },
          reminders_due: dismissed ? [] : [{ exam_id: exam.exam_id, kind_id: "d7", subject: "physics", name: exam.name, days: 7 }] });
      }
      if (path === "/v1/exam-dates" && method === "POST") return json(exam);
      if (path === `/v1/exam-dates/${exam.exam_id}` && method === "PATCH") { dismissed = true; return json(exam); }
      return null;
    });
    const dates = new ExamDateController(profiles);
    expect(await dates.add({ subject: "physics", name: " Physics paper 2 ", date: "2027-05-20", time: "09:00", reminders: true })).toBe(true);
    expect(asked[0]).toMatchObject({ method: "POST", body: { name: "Physics paper 2", subject: "physics", time: "09:00", reminders: true } });
    expect(dates.getView()).toMatchObject({ status: "ready", countdown: { days: 7, name: "Physics paper 2" }, reminders: [{ kind_id: "d7" }] });
    expect(await dates.dismiss(dates.getView().reminders[0]!)).toBe(true);
    expect(asked.find((a) => a.method === "PATCH")?.body).toEqual({ dismiss: "d7" });
    expect(dates.getView().reminders).toEqual([]);
  });
});
