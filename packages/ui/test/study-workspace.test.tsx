import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EMPTY_STUDY, type StudyWorkspaceController, type StudyWorkspaceView } from "@jana/client-core";
import { StudyWorkspace } from "../src/learn/StudyWorkspace.js";
afterEach(cleanup);
const sid = `src_${"0".repeat(26)}`, now = "2026-10-18T00:00:00Z";
const source = { source_id: sid, revision: 1, kind: "text", title: "Biology", state: "ready", private: false, created_at: now, updated_at: now, readable_units: 1, unreadable_units: [], sha256: "0".repeat(64) } as const;
const cited = (text: string) => ({ text, citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] });
function show(extra: Partial<StudyWorkspaceView>) {
  const view = { ...EMPTY_STUDY, status: "ready", ...extra } as StudyWorkspaceView;
  const controller = { subscribe: () => () => {}, getView: () => view, load: vi.fn(async () => {}), close: vi.fn(), open: vi.fn(), refreshOpened: vi.fn(), generate: vi.fn(async () => {}), rate: vi.fn(), submit: vi.fn(), readCitation: vi.fn(async () => true), playOverview: vi.fn(), stopReading: vi.fn(), loadTopics: vi.fn(), saveDraft: vi.fn(async () => {}), loadMaterialTopics: vi.fn(async () => {}), openSet: vi.fn(async () => {}), showAid: vi.fn(async () => {}), hideAid: vi.fn(), clearResult: vi.fn(), loadMedia: vi.fn(async () => null), seek: vi.fn() };
  render(<StudyWorkspace controller={controller as unknown as StudyWorkspaceController} />);
  return controller;
}
test("private material title is absent and opening requires confirmation", () => {
  const { title: _, state: __, sha256: ___, readable_units: ____, unreadable_units: _____, ...summary } = source;
  const controller = show({ sources: [{ ...summary, private: true }] });
  expect(screen.queryByText("Biology")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Private material" }));
  expect(controller.open).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Open material" }));
  expect(controller.open).toHaveBeenCalledWith(sid);
});
test("card answer and ratings require reveal; rating sends the selected source card", () => {
  const card = { card_id: `fcd_${"0".repeat(26)}`, revision: 1, suspended: false, front: cited("Which molecule stores genetic information?"), back: cited("DNA stores genetic information.") };
  const controller = show({ source, aid: { aid_id: `aid_${"0".repeat(26)}`, job_id: `stj_${"0".repeat(26)}`, kind: "flashcards", sources: [{ source_id: sid, revision: 1 }], title: "Biology", claims: [cited("From this material")], status: "ready", created_at: now, deck_id: `dek_${"0".repeat(26)}` }, deck: { deck_id: `dek_${"0".repeat(26)}`, aid_id: `aid_${"0".repeat(26)}`, source_id: sid, revision: 1, scheduler: "fsrs-6-source-v1", cards: [card] } });
  expect(screen.queryByText("DNA stores genetic information.")).toBeNull(); expect(screen.queryByRole("button", { name: "Good" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Reveal answer" }));
  expect(screen.getByText("DNA stores genetic information.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Good" })); expect(controller.rate).toHaveBeenCalledWith(card, "good");
});
test("study quiz allows skipped answers and submits only user-selected choices", () => {
  const controller = show({ source, aid: { aid_id: `aid_${"0".repeat(26)}`, job_id: `stj_${"0".repeat(26)}`, kind: "quiz", sources: [{ source_id: sid, revision: 1 }], title: "Biology", claims: [cited("From this material")], status: "ready", created_at: now, quiz_id: `sqz_${"0".repeat(26)}` }, quiz: { quiz_id: `sqz_${"0".repeat(26)}`, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", items: [{ item_id: "q1", type: "choice", stem: cited("Which molecule?"), options: [{ option_id: "a", text: "DNA" }, { option_id: "b", text: "Water" }] }] } });
  fireEvent.click(screen.getByRole("button", { name: "Submit quiz" })); expect(controller.submit).toHaveBeenLastCalledWith({});
  fireEvent.click(screen.getByRole("radio", { name: "DNA" })); fireEvent.click(screen.getByRole("button", { name: "Submit quiz" })); expect(controller.submit).toHaveBeenLastCalledWith({ q1: "a" });
});

test("material chat sends the learner's prompt and audio uses only the accepted overview", () => {
  const controller = show({ source, canSpeak: true, selections: [{ source_id: sid, revision: 1 }], aid: {
    aid_id: `aid_${"0".repeat(26)}`, job_id: `stj_${"0".repeat(26)}`, kind: "audio_overview", sources: [{ source_id: sid, revision: 1 }], title: "Biology overview", claims: [cited("Enzymes are catalysts.")], status: "ready", created_at: now,
  } });
  const field = screen.getByRole("textbox", { name: "Ask about this material" });
  fireEvent.change(field, { target: { value: "What do enzymes do?" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask material" }));
  expect(controller.generate).toHaveBeenCalledWith("chat", 10, false, true, "What do enzymes do?");
  fireEvent.click(screen.getByRole("button", { name: "Play overview" }));
  expect(controller.playOverview).toHaveBeenCalledTimes(1);
});

test("a submission request shows guided help without automatically generating an answer", () => {
  const controller = show({ source, error: "graded_work" });
  expect(screen.getByText(/I can't do graded work for you/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Help me understand the first question" }));
  expect((screen.getByRole("textbox", { name: "Ask about this material" }) as HTMLTextAreaElement).value).toBe("Help me understand the first question");
  expect(controller.generate).not.toHaveBeenCalled();
});

test("Study distress refusal shows the canned support text without repeating the disclosure", () => {
  show({ error: "safety_template", safetyTemplate: "tpl.distress" });
  expect(screen.getByText(/You deserve to be supported/)).toBeTruthy();
  expect(screen.queryByText(/could not complete/i)).toBeNull();
  expect(screen.queryByText(/emergency_number|child_helpline/)).toBeNull();
});

const aidBase = { job_id: `stj_${"0".repeat(26)}`, sources: [{ source_id: sid, revision: 1 }], title: "Biology", claims: [cited("From this material")], status: "ready", created_at: now } as const;

test("stu21_settings_respected: before material the tools are greyed with the reason", () => {
  show({ sources: [] });
  expect(screen.getByText("Add material to generate study tools")).toBeTruthy();
  expect((screen.getByRole("button", { name: /^Quiz/ }) as HTMLButtonElement).disabled).toBe(true);
});

test("stu21_settings_respected: a quiz's settings dialog sends its types, difficulty, topics and focus", () => {
  const controller = show({ source, materialTopics: [{ title: "Enzymes", chunk_ids: [`sck_${"0".repeat(26)}`] }, { title: "Respiration", chunk_ids: [`sck_${"1".repeat(26)}`] }] });
  for (const tool of ["Summary", "Quiz", "Flashcards", "Notes", "Podcast", "Lesson plan"]) expect(screen.getByRole("button", { name: new RegExp(`^${tool}`) })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /^Quiz/ }));
  const dialog = screen.getByRole("dialog", { name: "Quiz" });
  expect(dialog).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", { name: "Multiple choice" }));
  fireEvent.click(screen.getByRole("radio", { name: "Hard" }));
  fireEvent.click(screen.getByRole("button", { name: "Respiration" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Focus (optional)" }), { target: { value: "optimum temperature" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "How many questions (1–40)" }), { target: { value: "12" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(controller.generate).toHaveBeenCalledWith("quiz", 12, false, true, undefined, { question_types: ["fill_blank", "true_false"], difficulty: "hard", topics: ["Enzymes"], focus: "optimum temperature" });
});

test("stu21_settings_respected: a podcast takes its length and voices; a lesson plan its time", () => {
  const controller = show({ source });
  fireEvent.click(screen.getByRole("button", { name: /^Podcast/ }));
  fireEvent.click(screen.getByRole("radio", { name: "Short" }));
  fireEvent.click(screen.getByRole("radio", { name: "Two voices" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(controller.generate).toHaveBeenLastCalledWith("audio_overview", 10, false, true, undefined, { podcast_length: "short", voices: 2 });
  cleanup();
  const again = show({ source });
  fireEvent.click(screen.getByRole("button", { name: /^Lesson plan/ }));
  fireEvent.change(screen.getByRole("spinbutton", { name: "Minutes you have" }), { target: { value: "30" } });
  fireEvent.change(screen.getByLabelText("Ready by"), { target: { value: "2026-11-02" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(again.generate).toHaveBeenLastCalledWith("lesson_plan", 10, false, true, undefined, { minutes_available: 30, ready_by: "2026-11-02" });
});

test("stu21_sets_persist_progress: My Sets shows live progress and opens a set; a private set asks first", () => {
  const sets = [
    { aid_id: `aid_${"1".repeat(26)}`, kind: "quiz", sources: [{ source_id: sid, revision: 1 }], status: "ready", created_at: now, private: false, title: "Biology", progress: { questions_total: 8, questions_left: 5 } },
    { aid_id: `aid_${"2".repeat(26)}`, kind: "flashcards", sources: [{ source_id: sid, revision: 1 }], status: "ready", created_at: now, private: false, title: "Biology", progress: { cards_total: 20, cards_due_today: 12 } },
    { aid_id: `aid_${"3".repeat(26)}`, kind: "summary", sources: [{ source_id: sid, revision: 1 }], status: "ready", created_at: now, private: true },
  ] as StudyWorkspaceView["sets"];
  const controller = show({ sources: [source], sets });
  expect(screen.getByText("5 questions left")).toBeTruthy();
  expect(screen.getByText("12 cards due today")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Quiz · Biology/ }));
  expect(controller.openSet).toHaveBeenCalledWith(sets[0]);
  fireEvent.click(screen.getByRole("button", { name: /Summary · Private material/ }));
  expect(controller.openSet).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Open material" }));
  expect(controller.openSet).toHaveBeenLastCalledWith(sets[2]);
});

test("stu21_sets_persist_progress: a quiz opens with its draft and keeps each new answer", () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const controller = show({ source, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId }, quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", draft: { quiz_revision: 1, position: 1, answers: [{ item_id: "q1", answer: "true" }] }, items: [
    { item_id: "q1", type: "true_false", stem: cited("DNA stores genetic information.") },
    { item_id: "q2", type: "multi_select", stem: cited("Which are nucleic acids?"), options: [{ option_id: "a", text: "DNA" }, { option_id: "b", text: "RNA" }, { option_id: "c", text: "Glucose" }] },
    { item_id: "q3", type: "fill_blank", stem: cited("____ stores genetic information.") },
  ] } });
  expect((screen.getByRole("radio", { name: "True" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "DNA" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "RNA" }));
  expect(controller.saveDraft).toHaveBeenLastCalledWith({ q1: "true", q2: "a,b" }, 1);
  fireEvent.click(screen.getByRole("button", { name: "Submit quiz" }));
  expect(controller.submit).toHaveBeenLastCalledWith({ q1: "true", q2: "a,b" });
});

test("stu22_chapters_and_seek: chapters and transcript lines seek the player; the current line follows playback", () => {
  const recording = { ...source, kind: "recording", duration_ms: 120000 } as const;
  const chunks = [0, 60000].map((start, i) => ({ chunk_id: `sck_${String(i).repeat(26)}`, source_id: sid, revision: 1, ordinal: i, locator: { kind: "time", start_ms: start, end_ms: start + 60000 }, text: i ? "Respiration releases energy." : "Enzymes are catalysts.", sha256: "0".repeat(64) })) as StudyWorkspaceView["chunks"];
  const chapters = [{ start_ms: 0, end_ms: 60000, title: "Enzymes", summary: [cited("Enzymes speed up reactions.")] }, { start_ms: 60000, end_ms: 120000, title: "Respiration", summary: [cited("Respiration releases energy.")] }];
  const controller = show({ source: recording, chunks, playhead: { ms: 61000, seq: 1 }, aids: [{ ...aidBase, aid_id: `aid_${"4".repeat(26)}`, kind: "chapters", chapters }] });
  expect((screen.getByRole("checkbox", { name: "Auto scroll" }) as HTMLInputElement).checked).toBe(true);
  const line = (text: string) => screen.getByRole("button", { name: new RegExp(`\\d:\\d\\d\\s*${text}`) });
  // The playhead (a citation's moment) marks the line being played.
  expect(line("Respiration releases energy.").getAttribute("aria-current")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "1:00 · Respiration" }));
  expect(controller.seek).toHaveBeenLastCalledWith(60000);
  fireEvent.click(line("Enzymes are catalysts."));
  expect(controller.seek).toHaveBeenLastCalledWith(0);
  expect(line("Enzymes are catalysts.").getAttribute("aria-current")).toBe("true");
  fireEvent.click(screen.getAllByRole("button", { name: "Source 1" })[0]!);
  expect(controller.readCitation).toHaveBeenCalled();
});

test("asm28: a first wrong answer in a study quiz offers help and a second try, never the answer", () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const view = { source, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId }, quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cited("DNA is a protein.") }] },
    result: { attempt_id: `sqa_${"0".repeat(26)}`, results: [{ item_id: "q1", verdict: "incorrect", marking: "judged", label: "Judged, not checked", explanation: cited("DNA is a nucleic acid, the material says.") }] } } as const;
  const controller = show(view as unknown as Partial<StudyWorkspaceView>);
  expect(screen.queryByText("DNA is a nucleic acid, the material says.")).toBeNull();
  const results = within(screen.getByRole("region", { name: "Quiz results" }));
  expect(results.getByRole("group", { name: "Help with this question" })).toBeTruthy();
  fireEvent.click(results.getByRole("button", { name: "Give me a hint" }));
  expect((screen.getByRole("textbox", { name: "Ask about this material" }) as HTMLTextAreaElement).value).toContain("DNA is a protein.");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(controller.clearResult).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Show me the answer" }));
  expect(screen.getByText("DNA is a nucleic acid, the material says.")).toBeTruthy();
});
