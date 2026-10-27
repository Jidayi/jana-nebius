import { cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { StrictMode } from "react";
import { EMPTY_STUDY, type StudyWorkspaceController, type StudyWorkspaceView } from "@jana/client-core";
import { StudyWorkspace } from "../src/learn/StudyWorkspace.js";
afterEach(cleanup);
const sid = `src_${"0".repeat(26)}`, now = "2026-10-18T00:00:00Z";
const source = { source_id: sid, revision: 1, kind: "text", title: "Biology", state: "ready", private: false, created_at: now, updated_at: now, readable_units: 1, unreadable_units: [], sha256: "0".repeat(64) } as const;
const cited = (text: string) => ({ text, citations: [{ source_id: sid, revision: 1, chunk_id: `sck_${"0".repeat(26)}`, start: 0, end: 3, quote: "DNA" }] });
test("the native picker selection is kept until the upload has finished", async () => {
  const controller = show({});
  let finish!: () => void;
  controller.upload.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  const reset = vi.spyOn(input, "value", "set");
  fireEvent.change(input, { target: { files: [new File(["synthetic PDF"], "notes.pdf")] } });
  expect(controller.upload).toHaveBeenCalledTimes(1);
  expect(reset).not.toHaveBeenCalled();
  finish();
  await waitFor(() => expect(reset).toHaveBeenCalledWith(""));
  reset.mockRestore();
});
test("an unreadable notes photo offers text correction without finding the manage menu", () => {
  show({ source: { ...source, kind: "photo", state: "unreadable", readable_units: 0, unreadable_units: [1] } });
  fireEvent.click(screen.getByRole("button", { name: "Correct or replace source text" }));
  expect(screen.getByRole("textbox", { name: /Review the full readable text/ })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Save corrected revision" }).hasAttribute("disabled")).toBe(true);
});
test("photo correction shows the original beside editable text and saves a reviewed revision", async () => {
  const imageUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:notes-photo");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  try {
    const controller = show({ source: { ...source, kind: "photo", state: "unreadable", readable_units: 0, unreadable_units: [1] } });
    controller.loadPage.mockResolvedValue(new Blob(["synthetic image"], { type: "image/png" }));
    fireEvent.click(screen.getByRole("button", { name: "Correct or replace source text" }));
    expect(controller.loadPage).toHaveBeenCalledWith(1, 1, sid);
    expect((await screen.findByRole("img", { name: "Source page 1" })).getAttribute("src")).toBe("blob:notes-photo");
    fireEvent.change(screen.getByRole("textbox", { name: /Review the full readable text/ }), { target: { value: "x + 5 = 15. x = 10." } });
    fireEvent.click(screen.getByRole("button", { name: "Save corrected revision" }));
    await waitFor(() => expect(controller.correctText).toHaveBeenCalledWith("x + 5 = 15. x = 10."));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: /Review the full readable text/ })).toBeNull());
    expect(screen.getAllByRole("img", { name: "Source page 1" })).toHaveLength(1);
    cleanup();
    expect(revoke).toHaveBeenCalledWith("blob:notes-photo");
  } finally { imageUrl.mockRestore(); revoke.mockRestore(); }
});
test("unreadable scans allow previewing a page even when extraction produced no passages", () => {
  const controller = show({ source: { ...source, kind: "pdf", state: "unreadable", readable_units: 0, unreadable_units: [1, 2] } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Source page number" }), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "View source page 2" }));
  expect(controller.loadPage).toHaveBeenCalledWith(2, 1, sid);
});
test("returning to curriculum material waits for workspace setup and retains the pinned revision", async () => {
  const loads: Array<() => void> = [];
  const controller = { subscribe: () => () => {}, getView: () => EMPTY_STUDY,
    load: vi.fn(() => new Promise<void>((resolve) => loads.push(resolve))),
    close: vi.fn(), open: vi.fn(async () => {}) };
  const opened = vi.fn();
  render(<StrictMode><StudyWorkspace controller={controller as unknown as StudyWorkspaceController}
    initialSource={{ source_id: sid, revision: 2 }} onSourceOpened={opened} /></StrictMode>);
  expect(controller.open).not.toHaveBeenCalled();
  for (const resolve of loads) resolve();
  await waitFor(() => expect(controller.open).toHaveBeenCalledTimes(1));
  expect(controller.open).toHaveBeenCalledWith(sid, 2);
  expect(opened).toHaveBeenCalledTimes(1);
});
function show(extra: Partial<StudyWorkspaceView>, onReviewAccess?: () => void, onJourneyStarted?: (node: string, subject: string) => void, exampleMaterial?: () => Promise<File>) {
  const view = { ...EMPTY_STUDY, status: "ready", ...extra } as StudyWorkspaceView;
  const controller = { subscribe: () => () => {}, getView: () => view, load: vi.fn(async () => {}), close: vi.fn(), open: vi.fn(), refreshOpened: vi.fn(), generate: vi.fn(async () => {}), upload: vi.fn(async () => {}), addWeb: vi.fn(async () => {}), startExtraction: vi.fn(async () => {}), rate: vi.fn(), submit: vi.fn(), readCitation: vi.fn(async () => true), playOverview: vi.fn(), stopReading: vi.fn(), pauseOverview: vi.fn(), resumeOverview: vi.fn(), checkAnswer: vi.fn(async () => {}), jobAction: vi.fn(), loadTopics: vi.fn(async () => true), saveDraft: vi.fn(async () => {}), loadMaterialTopics: vi.fn(async () => {}), openSet: vi.fn(async () => {}), showAid: vi.fn(async () => {}), hideAid: vi.fn(), clearResult: vi.fn(), loadMedia: vi.fn(async () => null), seek: vi.fn(), archiveSources: vi.fn(async () => {}), requestQuizHelp: vi.fn(async () => {}) };
  const connected = { ...controller, loadPage: vi.fn(async (): Promise<Blob | null> => null), correctText: vi.fn(async (_text: string) => {}), beginJourney: vi.fn(async () => true) };
  render(<StudyWorkspace controller={connected as unknown as StudyWorkspaceController} {...(exampleMaterial ? { exampleMaterial } : {})} {...(onReviewAccess ? { onReviewAccess } : {})} {...(onJourneyStarted ? { onJourneyStarted } : {})} />);
  return connected;
}
test("a selected material objective starts its journey before handing off to curriculum learning", async () => {
  const onJourneyStarted = vi.fn();
  const node = "cur.phy.o.waves", kc = "kc.phy.o.waves.period";
  const controller = show({ source, followCurrent: true, topics: [{ node_id: node, title: "Waves", subject: "cur.phy.o", kc_ids: [kc], lesson_ids: [], objectives: [{ kc_id: kc, statement: "Calculate the period" }] }] }, undefined, onJourneyStarted);
  fireEvent.click(screen.getByRole("button", { name: "Start learning journey" }));
  expect(controller.beginJourney).toHaveBeenCalledWith(node, kc);
  await waitFor(() => expect(onJourneyStarted).toHaveBeenCalledWith(node, "cur.phy.o"));
  expect(controller.generate).not.toHaveBeenCalled();
});
test("web imports name Tavily, require consent, and reset that agreement if the URL changes", () => {
  const controller = show({ access: { status: "ready", needsGuardian: false } });
  fireEvent.click(screen.getByRole("button", { name: "Add a web link" }));
  const input = screen.getByRole("textbox", { name: "Public web page URL" });
  fireEvent.change(input, { target: { value: "https://www.britannica.com/place/Paris" } });
  const button = screen.getByRole("button", { name: "Import page with Tavily" });
  expect(button.hasAttribute("disabled")).toBe(true);
  const agree = screen.getByRole("checkbox", { name: /Send this public page URL to Tavily/ });
  fireEvent.click(agree);
  expect(button.hasAttribute("disabled")).toBe(false);
  fireEvent.change(input, { target: { value: "https://www.britannica.com/place/London" } });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(controller.addWeb).not.toHaveBeenCalled();
  fireEvent.click(agree);
  fireEvent.click(button);
  expect(controller.addWeb).toHaveBeenCalledWith("https://www.britannica.com/place/London");
});
test("lesson follow-up buttons retain the displayed lesson instead of losing their referent", async () => {
  const aid = { aid_id: `aid_${"0".repeat(26)}`, job_id: `stj_${"0".repeat(26)}`, kind: "chat" as const, title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [cited("DNA stores genetic information.")], status: "ready" as const, created_at: now };
  const controller = show({ source, aid, followCurrent: true });
  fireEvent.click(screen.getByRole("button", { name: "Explain a step" }));
  expect(screen.getByRole("textbox", { name: "Ask about this material" }).getAttribute("value") ?? (screen.getByRole("textbox", { name: "Ask about this material" }) as HTMLTextAreaElement).value).toBe("Can you explain that step again, a different way?");
  fireEvent.click(screen.getByRole("button", { name: "Ask material" }));
  await waitFor(() => expect(controller.generate).toHaveBeenCalledWith("chat", 10, false, true, "Can you explain that step again, a different way?", undefined, aid.aid_id));
  fireEvent.click(screen.getByRole("button", { name: "Make flashcards from this" }));
  expect(controller.generate).toHaveBeenLastCalledWith("flashcards", 10, false, true, undefined, undefined, aid.aid_id);
  expect(controller.saveDraft).not.toHaveBeenCalled();
});
test("flashcards continue into their own quiz using the existing settings and extraction review", async () => {
  const aidId = `aid_${"2".repeat(26)}`, deckId = `dek_${"2".repeat(26)}`;
  const controller = show({ source: { ...source, state: "partial" }, followCurrent: true,
    aid: { aid_id: aidId, job_id: `stj_${"2".repeat(26)}`, kind: "flashcards", title: "Biology", sources: [{ source_id: sid, revision: 1 }], claims: [cited("DNA stores genetic information.")], status: "ready", created_at: now, deck_id: deckId },
    deck: { deck_id: deckId, aid_id: aidId, source_id: sid, revision: 1, scheduler: "fsrs-6-source-v1", cards: [] } });
  fireEvent.click(screen.getByRole("button", { name: "Make a quiz" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getByText("Uses the learning points in the current study set, with references to your original material.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Generate", exact: true }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "I reviewed the extracted text. Use only the readable passages." }));
  fireEvent.click(screen.getByRole("button", { name: "Generate", exact: true }));
  await waitFor(() => expect(controller.generate).toHaveBeenCalledWith("quiz", 10, true, true, undefined, expect.objectContaining({ question_types: ["choice", "fill_blank", "true_false"] }), aidId));
  expect(controller.rate).not.toHaveBeenCalled();
  expect(controller.saveDraft).not.toHaveBeenCalled();
});
test("missing Study permission offers a next step while saved materials remain available", () => {
  const review = vi.fn();
  const controller = show({ sources: [source], access: { status: "consent_required", needsGuardian: true }, error: "consent_required" }, review);
  expect(screen.getByText("A parent or guardian needs to approve online Study for this student. You can still add files and read saved material here.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Review Study access" }));
  expect(review).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Biology Ready to study" }));
  expect(controller.open).toHaveBeenCalledWith(sid);
  expect(document.querySelector<HTMLInputElement>('input[type="file"]')!.disabled).toBe(false);
});
test("pending access explains the next step beside an uploaded source and prevents repeated failed processing", () => {
  show({ source: { ...source, state: "queued" }, access: { status: "consent_required", needsGuardian: false } }, vi.fn());
  expect(screen.getByRole("button", { name: "Review Study access" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Process material" }).hasAttribute("disabled")).toBe(true);
});
test("a successful extraction supersedes an older failure for the same source revision", () => {
  const job = { job_id: `stj_${"1".repeat(26)}`, kind: "extract", sources: [{ source_id: sid, revision: 1 }], state: "completed", completed_units: 69, total_units: 69, result_ids: [], error: null, created_at: now, updated_at: now } as const;
  show({ source, jobs: [job, { ...job, job_id: `stj_${"2".repeat(26)}`, state: "failed", error: "source_too_large" }] });
  expect(screen.queryByText(/exceeds the processing limit/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Activity" }));
  expect(screen.getByRole("status").textContent).toContain("Completed");
  expect(screen.queryByText(/exceeds the processing limit/)).toBeNull();
});
test("PDF picker and drop both request online extraction", () => {
  const controller = show({});
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["synthetic PDF"], "notes.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.drop(input.closest("label")!, { dataTransfer: { files: [file] } });
  expect(controller.upload.mock.calls).toEqual([[file, undefined, true], [file, undefined, true]]);
});
test("an already uploaded PDF is processed online", () => {
  const controller = show({ source: { ...source, kind: "pdf", state: "queued" } });
  fireEvent.click(screen.getByRole("button", { name: "Process material" }));
  expect(controller.startExtraction).toHaveBeenCalledWith(true);
});
test("complete remote extraction asks for review without claiming pages were unreadable", () => {
  show({ source: { ...source, kind: "pdf", state: "partial", readable_units: 69, unreadable_units: [] } });
  expect(screen.getByText("All pages were extracted. You can review the text here; each tool asks you to confirm it before generating.")).toBeTruthy();
  expect(screen.queryByText(/Some source units could not be read/)).toBeNull();
  expect(screen.getByRole("button", { name: /^Summary/ }).hasAttribute("disabled")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: /^Summary/ }));
  expect(screen.getByRole("button", { name: "Generate" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "I reviewed the extracted text. Use only the readable passages." }));
  expect(screen.getByRole("button", { name: "Generate" }).hasAttribute("disabled")).toBe(false);
});
test("readable PDF awaiting review can check curriculum matches and show source-based fallback", async () => {
  const controller = show({ source: { ...source, kind: "pdf", state: "partial", readable_units: 69, unreadable_units: [] }, followCurrent: true });
  const lookup = screen.getByRole("button", { name: "Find related syllabus topics" });
  expect(lookup.hasAttribute("disabled")).toBe(false);
  fireEvent.click(lookup);
  await screen.findByText(/No reliable match to an installed curriculum topic/);
  expect(controller.loadTopics).toHaveBeenCalledOnce();
  expect(controller.generate).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: /^Summary/ }).hasAttribute("disabled")).toBe(false);
});
test("failed lookup does not claim that no curriculum topic matches", async () => {
  const controller = show({ source, followCurrent: true });
  controller.loadTopics.mockResolvedValueOnce(false);
  fireEvent.click(screen.getByRole("button", { name: "Find related syllabus topics" }));
  await waitFor(() => expect(controller.loadTopics).toHaveBeenCalledOnce());
  expect(screen.queryByText(/No reliable match to an installed curriculum topic/)).toBeNull();
});
test.each(["resume", "replace"])("PDF %s keeps online extraction", (action) => {
  const pdf = { ...source, kind: "pdf" as const, state: action === "resume" ? "uploading" as const : "ready" as const };
  const controller = show({ source: pdf });
  if (action === "replace") fireEvent.click(screen.getByRole("button", { name: "Manage material" }));
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["synthetic PDF"], "notes.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  expect(controller.upload).toHaveBeenCalledWith(...(action === "replace" ? [file, pdf, true, true] : [file, pdf, true]));
});
test("private material title is absent and opening requires confirmation", () => {
  const { title: _, state: __, sha256: ___, readable_units: ____, unreadable_units: _____, ...summary } = source;
  const controller = show({ sources: [{ ...summary, private: true }] });
  expect(screen.queryByText("Biology")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Private material Private material" }));
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
  fireEvent.click(screen.getByRole("button", { name: "Settings: Quiz" }));
  const dialog = screen.getByRole("dialog", { name: "Quiz" });
  expect(dialog).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", { name: "Multiple choice" }));
  fireEvent.click(screen.getByRole("radio", { name: "Hard" }));
  fireEvent.click(screen.getByText("Choose specific topics (optional)"));
  fireEvent.click(screen.getByRole("checkbox", { name: "Limit this tool to selected topics" }));
  fireEvent.click(screen.getByRole("button", { name: "Respiration" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Focus (optional)" }), { target: { value: "optimum temperature" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "How many questions (1–40)" }), { target: { value: "12" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(controller.generate).toHaveBeenCalledWith("quiz", 12, false, true, undefined, { question_types: ["fill_blank", "true_false"], difficulty: "hard", topics: ["Enzymes"], focus: "optimum temperature" });
});

test("stu21_settings_respected: a podcast takes its length and voices; a lesson plan its time", () => {
  const controller = show({ source });
  fireEvent.click(screen.getByRole("button", { name: "Settings: Podcast" }));
  fireEvent.click(screen.getByRole("radio", { name: "Short" }));
  fireEvent.click(screen.getByRole("radio", { name: "Two voices" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(controller.generate).toHaveBeenLastCalledWith("audio_overview", 10, false, true, undefined, { podcast_length: "short", voices: 2 });
  cleanup();
  const again = show({ source });
  fireEvent.click(screen.getByRole("button", { name: "Settings: Lesson plan" }));
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
  fireEvent.click(screen.getByRole("button", { name: "All study sets" }));
  expect(screen.getByText("5 questions left")).toBeTruthy();
  expect(screen.getByText("12 cards due today")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Quiz · Biology/ }));
  expect(controller.openSet).toHaveBeenCalledWith(sets[0]);
  fireEvent.click(screen.getByRole("button", { name: "All study sets" }));
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
  fireEvent.click(screen.getByRole("checkbox", { name: "Show all questions" }));
  expect((screen.getByRole("radio", { name: "True" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "DNA" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "RNA" }));
  expect(controller.saveDraft).toHaveBeenLastCalledWith({ q1: "true", q2: "a,b" }, 1);
  fireEvent.click(screen.getByRole("button", { name: "Submit quiz" }));
  expect(controller.submit).toHaveBeenLastCalledWith({ q1: "true", q2: "a,b" });
});

test("a reopened submitted quiz shows the learner's actual answer beside its saved feedback", () => {
  const aidId = `aid_${"0".repeat(26)}`, quizId = `sqz_${"0".repeat(26)}`;
  show({ source, aid: { ...aidBase, aid_id: aidId, kind: "quiz", quiz_id: quizId },
    quiz: { quiz_id: quizId, aid_id: aidId, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cited("DNA stores genetic information.") }] },
    result: { attempt_id: `sqa_${"0".repeat(26)}`, results: [{ item_id: "q1", verdict: "correct", marking: "judged", label: "Judged, not checked", explanation: cited("DNA stores genetic information.") }] },
    resultAnswers: { q1: "true" } });
  const chosen = screen.getByRole("radio", { name: "True" }) as HTMLInputElement;
  expect(chosen.checked).toBe(true);
  expect(chosen.closest("fieldset")?.disabled).toBe(true);
  expect(screen.getByText("Correct")).toBeTruthy();
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
  fireEvent.click(screen.getAllByRole("button", { name: "Biology · At 00:00" })[0]!);
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
  expect(controller.requestQuizHelp).toHaveBeenCalledWith("q1", "hint", false);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(controller.clearResult).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Show me the answer" }));
  expect(screen.getByText("DNA is a nucleic acid, the material says.")).toBeTruthy();
});


test("whole-document generation omits preview topics unless the learner explicitly narrows them", () => {
  const controller = show({ source, materialTopics: [{ title: "Cover page", chunk_ids: [`sck_${"0".repeat(26)}`] }] });
  fireEvent.click(screen.getByRole("button", { name: "Settings: Summary" }));
  expect(screen.getByText("Uses the whole material. Leave the optional focus blank to cover the full document.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(controller.generate).toHaveBeenCalledWith("summary", 10, false, true, undefined, {});
});

test("a running tool explains progress, prevents duplicate clicks and keeps other tools available", () => {
  const job = { job_id: `stj_${"1".repeat(26)}`, kind: "summary", sources: [{ source_id: sid, revision: 1 }], state: "running", completed_units: 69, total_units: 81, result_ids: [], error: null, created_at: now, updated_at: now } as const;
  show({ source, jobs: [job] });
  expect(screen.getByText(/Reading and checking the material in sections/)).toBeTruthy();
  expect(screen.getByRole("button", { name: /^Summary/ }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: /^Flashcards/ }).hasAttribute("disabled")).toBe(false);
});


test("partial-source chat offers its review beside the composer and sends only after confirmation", () => {
  const controller = show({ source: { ...source, state: "partial" }, selections: [{ source_id: sid, revision: 1 }] });
  fireEvent.click(screen.getByRole("tab", { name: "Chat" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Ask about this material" }), { target: { value: "What is DNA?" } });
  const send = screen.getByRole("button", { name: "Ask material" });
  expect(send.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "I reviewed the extracted text. Use only the readable passages." }));
  expect(send.hasAttribute("disabled")).toBe(false);
  fireEvent.click(send);
  expect(controller.generate).toHaveBeenCalledWith("chat", 10, true, true, "What is DNA?");
});

test("a completed job remains openable from history without generating or spending again", () => {
  const aid = { ...aidBase, aid_id: `aid_${"1".repeat(26)}`, kind: "summary" as const };
  const job = { job_id: aid.job_id, kind: "summary", sources: [{ source_id: sid, revision: 1 }], state: "completed", completed_units: 3, total_units: 3, result_ids: [aid.aid_id], error: null, created_at: now, updated_at: now } as const;
  const controller = show({ source, aids: [aid], jobs: [job] });
  fireEvent.click(screen.getByRole("button", { name: "Activity" }));
  fireEvent.click(screen.getByRole("button", { name: "Open result" }));
  expect(controller.showAid).toHaveBeenCalledWith(aid.aid_id);
  expect(screen.queryByRole("dialog", { name: "Activity" })).toBeNull();
  expect(controller.generate).not.toHaveBeenCalled();
});


test("NVIDIA Podcast keeps Play disabled while readiness loads and discloses cloud trial retention", () => {
  show({ source, busy: true, canSpeak: true, podcastVoice: { enabled: true, configured: true },
    aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "audio_overview" } });
  expect(screen.getByRole("button", { name: "Play overview" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByText(/NVIDIA Magpie neural voice/)).toBeTruthy();
  expect(screen.getByText(/NVIDIA’s free trial may retain text and audio/)).toBeTruthy();
  expect(screen.queryByText("Read on this computer using an installed voice.")).toBeNull();
});

test("quick generation uses whole-material defaults; duplicate sets offer Open instead of spending again", () => {
  const controller = show({ source, selections: [{ source_id: sid, revision: 1 }], aids: [{ ...aidBase, aid_id: `aid_${"1".repeat(26)}`, kind: "summary" }] });
  fireEvent.click(screen.getByRole("button", { name: /^Summary The/ }));
  expect(screen.getByRole("dialog", { name: "This study set already exists" })).toBeTruthy();
  expect(controller.generate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Open existing set" }));
  expect(controller.showAid).toHaveBeenCalledWith(`aid_${"1".repeat(26)}`);
});

test("quick quiz uses defaults without opening settings", () => {
  const controller = show({ source });
  fireEvent.click(screen.getByRole("button", { name: /^Quiz Questions/ }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(controller.generate).toHaveBeenCalledWith("quiz", 10, false, true, undefined, { question_types: ["choice", "fill_blank", "true_false"], difficulty: "medium" });
});

test("old failed jobs remain actionable in Activity without crowding the open Podcast", () => {
  const failed = { job_id: `stj_${"1".repeat(26)}`, kind: "flashcards", sources: [{ source_id: sid, revision: 1 }], state: "failed", completed_units: 0, total_units: 81, result_ids: [], error: "insufficient_evidence", created_at: now, updated_at: now } as const;
  show({ source, jobs: [failed], aid: { ...aidBase, aid_id: `aid_${"2".repeat(26)}`, kind: "audio_overview" } });
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Activity" }));
  const history = screen.getByRole("dialog", { name: "Activity" });
  expect(within(history).getByRole("button", { name: "Try again" })).toBeTruthy();
  expect(within(history).getByText("Details").closest("details")!.open).toBe(false);
});

test("summary templates retain whole-document scope and citations in a bounded style request", () => {
  const controller = show({ source });
  fireEvent.click(screen.getByRole("button", { name: "Settings: Summary" }));
  fireEvent.click(screen.getByRole("radio", { name: "Cheat sheet" }));
  fireEvent.click(screen.getByRole("button", { name: "Generate" }));
  expect(controller.generate).toHaveBeenCalledWith("summary", 10, false, true, undefined, { focus: expect.stringContaining("cover the whole material") });
});

test("focused quiz restores its question, navigates without losing answers, and retains Show all", () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const controller = show({ source, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId }, quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", draft: { quiz_revision: 1, position: 1, answers: [{ item_id: "q1", answer: "true" }] }, items: [{ item_id: "q1", type: "true_false", stem: cited("First question") }, { item_id: "q2", type: "fill_blank", stem: cited("Second question") }] } });
  expect(screen.queryByText("First question")).toBeNull();
  expect(screen.getByText("Question 2 of 2")).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "Your word or phrase" }), { target: { value: "DNA" } });
  fireEvent.click(screen.getByRole("button", { name: "Check answer" }));
  expect(controller.checkAnswer).toHaveBeenCalledWith("q2", "DNA");
  fireEvent.click(screen.getByRole("button", { name: "Previous question" }));
  expect((screen.getByRole("radio", { name: "True" }) as HTMLInputElement).checked).toBe(true);
  expect(controller.saveDraft).toHaveBeenCalledWith({ q1: "true", q2: "DNA" }, 0);
  fireEvent.click(screen.getByRole("checkbox", { name: "Show all questions" }));
  expect(screen.getByText("Second question")).toBeTruthy();
});

test("a newly failed request stays actionable until the learner opens another result", () => {
  const jobId = `stj_${"1".repeat(26)}`;
  const failed = { job_id: jobId, kind: "summary", sources: [{ source_id: sid, revision: 1 }], state: "failed", completed_units: 0, total_units: 81, result_ids: [], error: "insufficient_evidence", created_at: now, updated_at: now } as const;
  const controller = show({ source, jobs: [failed], requestedJobId: jobId });
  const retry = screen.getByRole("button", { name: "Try again" });
  expect(retry.closest("details")).toBeNull();
  fireEvent.click(retry);
  expect(controller.jobAction).toHaveBeenCalledWith(jobId, "retry");
});

test("summary sections identify their source pages and preserve every citation", () => {
  const chunkId = `sck_${"0".repeat(26)}`;
  const controller = show({ source, chunks: [{ chunk_id: chunkId, source_id: sid, revision: 1, ordinal: 0, text: "DNA", locator: { kind: "page", page: 4 } }], aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "summary" } });
  expect(screen.getByRole("heading", { name: "Page 4" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Biology · Page 4" }));
  expect(controller.readCitation).toHaveBeenCalled();
});

test("a PDF reference opens the original page while preserving its exact highlighted evidence", async () => {
  const ref = cited("fact").citations[0]!;
  const controller = show({ source: { ...source, kind: "pdf" }, chunks: [{ chunk_id: ref.chunk_id, source_id: sid, revision: 1, ordinal: 0, text: "DNA", locator: { kind: "page", page: 23 } }], aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "summary" } });
  const loadPage = vi.fn(async () => null);
  Object.assign(controller, { loadPage });
  fireEvent.click(screen.getByRole("button", { name: "Biology · Page 23" }));
  await waitFor(() => expect(loadPage).toHaveBeenCalledWith(23, 1, sid));
  expect(controller.readCitation).toHaveBeenCalledWith(ref);
  expect(document.querySelector("mark")?.textContent).toBe("DNA");
});

test("equivalent quiz type orders reuse a known set with the same question count", () => {
  const aidId = `aid_${"1".repeat(26)}`;
  const controller = show({ source, selections: [{ source_id: sid, revision: 1 }], aids: [{ ...aidBase, aid_id: aidId, kind: "quiz", settings: { difficulty: "medium", question_types: ["true_false", "choice", "fill_blank"] } }], sets: [{ aid_id: aidId, kind: "quiz", sources: aidBase.sources, title: "Biology", private: false, status: "ready", created_at: now, progress: { questions_total: 10, questions_left: 8 } }] });
  fireEvent.click(screen.getByRole("button", { name: /^Quiz Questions/ }));
  expect(screen.getByRole("dialog", { name: "This study set already exists" })).toBeTruthy();
  expect(controller.generate).not.toHaveBeenCalled();
});


test("Study quiz help sends a question-aware request directly, with just the two reference shortcuts", () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const controller = show({ source, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId }, quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cited("DNA is a protein.") }, { item_id: "q2", type: "fill_blank", stem: cited("____ stores information.") }] } });
  expect(screen.getAllByRole("button", { name: "Give me a hint" })).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Explain simply" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Walk me through it" }));
  expect(controller.requestQuizHelp).toHaveBeenLastCalledWith("q1", "walk_through", false);
  fireEvent.click(screen.getByRole("button", { name: "Next question" }));
  fireEvent.click(screen.getByRole("button", { name: "Give me a hint" }));
  expect(controller.requestQuizHelp).toHaveBeenLastCalledWith("q2", "hint", false);
  expect(controller.generate).not.toHaveBeenCalled();
});

test("partial PDF help exposes review where requested and never silently confirms it", () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const controller = show({ source: { ...source, kind: "pdf", state: "partial" }, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId }, quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", items: [{ item_id: "q1", type: "true_false", stem: cited("DNA is a protein.") }] } });
  fireEvent.click(screen.getByRole("button", { name: "Give me a hint" }));
  const dialog = screen.getByRole("dialog", { name: "Review material for help" });
  expect(controller.requestQuizHelp).not.toHaveBeenCalled();
  expect(within(dialog).getByRole("button", { name: "Get help" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(within(dialog).getByRole("checkbox"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Get help" }));
  expect(controller.requestQuizHelp).toHaveBeenCalledWith("q1", "hint", true);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("coaching stays beside its quiz with source access and does not replace a saved answer", () => {
  const quizId = `sqz_${"0".repeat(26)}`;
  const controller = show({ source, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId }, quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", draft: { quiz_revision: 1, position: 0, answers: [{ item_id: "q1", answer: "false" }] }, items: [{ item_id: "q1", type: "true_false", stem: cited("DNA is a protein.") }, { item_id: "q2", type: "true_false", stem: cited("Cells use energy.") }] }, quizHelp: { quizId, itemId: "q1", kind: "hint", jobId: aidBase.job_id, aid: { ...aidBase, aid_id: `aid_${"1".repeat(26)}`, kind: "chat", claims: [cited("Which category does the material assign to DNA?")] } } });
  const help = screen.getByRole("region", { name: "Help with this question" });
  expect(within(help).getByText("Which category does the material assign to DNA?")).toBeTruthy();
  expect((screen.getByRole("radio", { name: "False" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "Ask about this material" }), { target: { value: "Explain that first step again" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask material" }));
  expect(controller.requestQuizHelp).toHaveBeenCalledWith("q1", "hint", false, "Explain that first step again");
  expect(controller.generate).not.toHaveBeenCalled();
  fireEvent.click(within(help).getByRole("button", { name: "Biology · Reference 1" }));
  expect(controller.readCitation).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Next question" }));
  expect(screen.queryByRole("region", { name: "Help with this question" })).toBeNull();
});

test.each(["hint", "walk_through"] as const)("unverified choice %s offers labelled general guidance without changing the draft", (kind) => {
  const quizId = `sqz_${"0".repeat(26)}`, jobId = aidBase.job_id;
  const controller = show({ source, aid: { ...aidBase, aid_id: `aid_${"0".repeat(26)}`, kind: "quiz", quiz_id: quizId },
    jobs: [{ job_id: jobId, kind: "chat", sources: [{ source_id: sid, revision: 1 }], state: "failed", completed_units: 0, total_units: 5, result_ids: [], error: "insufficient_evidence", created_at: now, updated_at: now }],
    quiz: { quiz_id: quizId, aid_id: `aid_${"0".repeat(26)}`, revision: 1, status: "ready", draft: { quiz_revision: 1, position: 0, answers: [{ item_id: "q1", answer: "b" }] }, items: [{ item_id: "q1", type: "choice", stem: cited("What stores genetic information?"), options: [{ option_id: "a", text: "DNA" }, { option_id: "b", text: "Water" }] }] },
    quizHelp: { quizId, itemId: "q1", kind, jobId, aid: null } });
  const help = screen.getByRole("region", { name: "Help with this question" });
  expect(within(help).getByText(/General study strategy/)).toBeTruthy();
  expect(within(help).queryByText(/DNA|Water/)).toBeNull();
  expect((screen.getByRole("radio", { name: "Water" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(within(help).getByRole("button", { name: "Let me try the question" }));
  expect((screen.getByRole("radio", { name: "Water" }) as HTMLInputElement).checked).toBe(true);
  expect(controller.submit).not.toHaveBeenCalled();
  expect(controller.checkAnswer).not.toHaveBeenCalled();
});

test("Home's saved activity opens after Study mounting, not during its cleanup", async () => {
  const { StrictMode } = await import("react");
  const view = { ...EMPTY_STUDY, status: "ready" } as StudyWorkspaceView;
  let pending: (() => void)[] = [];
  const controller = { subscribe: () => () => {}, getView: () => view,
    load: vi.fn(() => new Promise<void>((resolve) => { pending.push(resolve); })),
    close: vi.fn(), continueJourney: vi.fn(async () => {}), loadAccess: vi.fn(async () => {}),
  };
  const opened = vi.fn();
  render(<StrictMode><StudyWorkspace controller={controller as unknown as StudyWorkspaceController} initialJourney="lesson" onJourneyOpened={opened} /></StrictMode>);
  expect(controller.continueJourney).not.toHaveBeenCalled();
  expect(controller.close).toHaveBeenCalled();
  pending.forEach((resolve) => resolve()); pending = [];
  await waitFor(() => expect(controller.continueJourney).toHaveBeenCalledOnce());
  expect(controller.continueJourney).toHaveBeenCalledWith("lesson");
  expect(opened).toHaveBeenCalledOnce();
});

test("revealed rating buttons show native interval previews without recording a review", () => {
  const card = { card_id: `fcd_${"0".repeat(26)}`, revision: 1, suspended: false, front: cited("Which molecule stores genetic information?"), back: cited("DNA stores genetic information."), review_intervals_ms: { again: 120_000, hard: 86_400_000, good: 172_800_000, easy: 691_200_000 } };
  const aidId = `aid_${"0".repeat(26)}`, deckId = `dek_${"0".repeat(26)}`;
  const controller = show({ source, aid: { aid_id: aidId, job_id: `stj_${"0".repeat(26)}`, kind: "flashcards", sources: [{ source_id: sid, revision: 1 }], title: "Biology", claims: [cited("From this material")], status: "ready", created_at: now, deck_id: deckId }, deck: { deck_id: deckId, aid_id: aidId, source_id: sid, revision: 1, scheduler: "fsrs-6-source-v1", cards: [card] } });
  expect(screen.queryByRole("button", { name: "Good · 2 days" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Reveal answer" }));
  for (const name of ["Again · 2 min", "Hard · 1 day", "Good · 2 days", "Easy · 8 days"]) expect(screen.getByRole("button", { name })).toBeTruthy();
  expect(controller.rate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Good · 2 days" }));
  expect(controller.rate).toHaveBeenCalledWith(card, "good");
});

test("example scanned notes use the real upload path only when requested", async () => {
  const file = new File(["synthetic scan"], "example.pdf", { type: "application/pdf" });
  const load = vi.fn(async () => file);
  const controller = show({}, undefined, undefined, load);
  expect(load).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Use example scanned notes" }));
  await waitFor(() => expect(controller.upload).toHaveBeenCalledWith(file, undefined, true));
});
test("example fetch failure is visible and does not create an upload", async () => {
  const controller = show({}, undefined, undefined, async () => { throw new Error("offline"); });
  fireEvent.click(screen.getByRole("button", { name: "Use example scanned notes" }));
  expect(await screen.findByText("The example notes could not be opened. Try again or choose your own file.")).toBeTruthy();
  expect(controller.upload).not.toHaveBeenCalled();
});
test("leaving the workspace cancels an example that is still loading", async () => {
  let finish!: (file: File) => void;
  const controller = show({}, undefined, undefined, () => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Use example scanned notes" }));
  cleanup();
  finish(new File(["scan"], "example.pdf"));
  await Promise.resolve();
  expect(controller.upload).not.toHaveBeenCalled();
});
