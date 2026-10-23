// UXS-01 (recent sessions in the sidebar, grouped by day) and UXS-12 (Home's sessions to pick up and today's practice
// from the learner model's KC states), over synthetic lists and maps.
import { describe, expect, test } from "vitest";
import type { Session } from "@jana/contracts-ts";
import { CLIENT_KEYS, SessionController, duePractice, groupSessions, lastWorked, recentSessions, refreshesDue, sessionGroupOf, type KcState, type SubjectMap } from "../src/index.js";

const NOW = new Date(2026, 9, 15, 18, 30).getTime();
const DAY = 86_400_000;

function session(id: string, updated: number, extra: Partial<Session> = {}): Session {
  return { session_id: id, title: `Question ${id}`, mode: "guided", subject: "physics", topic_id: null, created_ts: 0, updated_ts: updated, archived: false, ...extra };
}

function map(subject: SubjectMap["subject"], states: KcState[]): SubjectMap {
  return {
    subject_id: `cur.${subject.slice(0, 3)}.o`, subject, level: "O", title: null, status: "ready", pack: null,
    sections: [{ node_id: "sec", code: "1", title: "Section", topics: [{
      node_id: `top.${subject}`, code: "1.1", title: "Topic", lessons: [],
      kcs: states.map((state, i) => ({ kc_id: `kc.${subject}.${i}`, code: `${i}`, statement: `Idea ${i}`, state, band: "learning" as const })),
    }] }],
  };
}

describe("UXS-01", () => {
  test("test_uxs01_recent_sessions_grouped_by_day", () => {
    const list = {
      next_before: null,
      sessions: [
        session("old", NOW - 30 * DAY),
        session("today", NOW - 60_000),
        session("gone", NOW, { archived: true }),
        session("yesterday", NOW - DAY),
        session("week", NOW - 3 * DAY),
      ],
    };
    const recent = recentSessions(list);
    expect(recent.map((s) => s.session_id)).toEqual(["today", "yesterday", "week", "old"]); // newest first, archived left out
    expect(groupSessions(recent, NOW).map((g) => [g.group, g.sessions.map((s) => s.session_id)])).toEqual([
      ["today", ["today"]], ["yesterday", ["yesterday"]], ["week", ["week"]], ["older", ["old"]],
    ]);
    // Day groups follow the local calendar: just after midnight, a session from late last night is yesterday's.
    const midnight = new Date(2026, 9, 15, 0, 5).getTime();
    expect(sessionGroupOf(midnight - 10 * 60_000, midnight)).toBe("yesterday");
    expect(recentSessions(list, 2)).toHaveLength(2);
    expect(recentSessions(null)).toEqual([]);
    // A blank session opened and never used is not listed; one used before its first question keeps its place.
    const blank = { next_before: null, sessions: [session("blank", 5, { title: "", created_ts: 5 }), session("used", 9, { title: "", created_ts: 5 }), session("asked", 7)] };
    expect(recentSessions(blank).map((s) => s.session_id)).toEqual(["used", "asked"]);
    expect(recentSessions({ next_before: null, sessions: Array.from({ length: 300 }, (_, i) => session(`s${i}`, i)) })).toHaveLength(CLIENT_KEYS.ui_recent_sessions_max);
  });
});

describe("UXS-12", () => {
  test("test_uxs12_due_practice_from_kc_states", () => {
    const maps = [map("physics", ["mastered", "learning", "not_started"]), map("chemistry", ["ready_to_check", "needs_review", "moved_on"])];
    const due = duePractice(maps);
    // A due refresh first, then nearly secure, then learning; mastered, not started and moved on are never suggested.
    expect(due.map((d) => [d.subject, d.kc.state])).toEqual([["chemistry", "needs_review"], ["chemistry", "ready_to_check"], ["physics", "learning"]]);
    expect(due[0]?.topicId).toBe("top.chemistry");
    expect(duePractice(maps, 1)).toHaveLength(1);
    expect(duePractice([{ ...maps[1]!, status: "unverified" }])).toEqual([]);
    expect(refreshesDue(maps)).toBe(1);
  });
});

describe("UXS-14", () => {
  test("test_uxs14_tutor_subject_is_the_last_worked", async () => {
    // The core lists sessions newest created first; the student created Chemistry last but then went back to Physics.
    const listed = [session("ses_b", NOW - DAY, { subject: "chemistry" }), session("ses_a", NOW, { subject: "physics" }), session("ses_c", NOW + 1, { subject: "mathematics", archived: true })];
    expect(lastWorked(listed)?.subject).toBe("physics");
    expect(lastWorked([])).toBeNull();
    const fetch = (async () => new Response(JSON.stringify({ sessions: listed, next_before: null }), { status: 200, headers: { "content-type": "application/json" } })) as typeof globalThis.fetch;
    const latest = await SessionController.latest({ endpoint: async () => ({ baseUrl: "http://127.0.0.1:9", token: "t" }) }, { fetch });
    expect(latest?.session_id).toBe("ses_a");
  });

  test("an asked session continues after its topic was diagnosed, and a lesson's only on its own topic (D94)", async () => {
    // Newest created first: a lesson on motion, an asked session the engine gave a topic, an older asked one.
    const listed = [
      session("ses_lesson", NOW, { topic_id: "cur.phy.o.motion", origin: "lesson" }),
      session("ses_asked", NOW - DAY, { topic_id: "cur.phy.o.motion", origin: "ask" }),
      session("ses_older", NOW - 2 * DAY, { origin: "ask" }),
    ];
    const posted: unknown[] = [];
    const fetch = (async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({ session_id: "ses_new", cursor: { epoch: "e", seq: 0 } }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ sessions: listed, next_before: null }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof globalThis.fetch;
    const launch = { endpoint: async () => ({ baseUrl: "http://127.0.0.1:9", token: "t" }) };
    const ask = { mode: "guided" as const, subject: "physics" as const, level: "O" as const, origin: { kind: "ask" as const, ref: null } };
    expect(await SessionController.resume(launch, ask, { fetch })).toBe("ses_asked");
    const lesson = { ...ask, topic_id: "cur.phy.o.motion", origin: { kind: "lesson" as const, ref: "les.phy.o.motion" } };
    expect(await SessionController.resume(launch, lesson, { fetch })).toBe("ses_lesson");
    // A core older than API 1.5 names no origin: subject and topic match as before.
    listed.splice(0, listed.length, session("ses_untyped", NOW, { topic_id: "cur.phy.o.motion" }));
    expect(await SessionController.resume(launch, ask, { fetch })).toBe("ses_new");
    expect(posted).toHaveLength(1);
  });
});
