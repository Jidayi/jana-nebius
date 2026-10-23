// ASM-27 and LRN-44 on screen: an imported past paper's report says how every mark was decided (judged marks labelled
// so) and that a practice paper never changes mastery, its questions keep their own numbers and diagrams, and Home's
// countdown names the nearest exam in plain words. Rendered from the gallery's data-only states (engine output).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { GalleryView, STATES } from "../gallery/index.js";
import { EMPTY_MOCKS, type MockView, type PastPaperSummary } from "@jana/client-core";
import { ExamCountdownCard } from "../src/mock/PastPapers.js";
import { MockContent, type MockActions } from "../src/mock/MockExam.js";
import { LocaleProvider } from "../src/i18n.js";

afterEach(() => cleanup());

const state = (id: string) => {
  const found = STATES.find((s) => s.id === id);
  expect(found, id).toBeDefined();
  return found!;
};

describe("ASM-27", () => {
  test("test_asm27_report_labels_how_each_mark_was_decided", () => {
    const { container } = render(<GalleryView state={state("mock-sitting.canonical.past-paper")} />);
    const marks = [...container.querySelectorAll("[data-marking]")].map((n) => n.getAttribute("data-marking"));
    expect(new Set(marks)).toEqual(new Set(["checked", "key", "judged"]));
    expect(container.textContent).toContain("Judged, not checked");
    expect(container.querySelector("[data-past-paper-note]")?.textContent).toContain("never change your mastery");
    // Marks lost by topic lead into practice, as for a mock.
    expect(container.querySelector('[data-topic-id="cur.phy.o.matter"]')?.textContent).toContain("Practise this");
  });

  test("test_asm27_questions_keep_their_numbers_and_diagrams", () => {
    const { container } = render(<GalleryView state={state("mock-sitting.canonical.past-paper-question")} />);
    expect(container.querySelector("[data-number-label]")?.getAttribute("data-number-label")).toBe("3");
    expect(container.querySelector("[data-paper-figure]")?.textContent).toContain("page 1 of the paper");
  });

  test("test_asm27_import_shows_the_marking_before_sitting", () => {
    const { container } = render(<GalleryView state={state("past-papers.canonical")} />);
    expect(container.querySelectorAll("[data-past-paper-found] li")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: /Import a past paper/ }));
    expect(container.querySelector("[data-past-paper-form]")?.textContent).toContain("Links aren't opened here");
  });
});

function placed(id: string, onHelp: MockActions["onHelp"]) {
  const payload = state(id).payload as { view: Partial<MockView>; pastPapers: PastPaperSummary[] };
  const noop = () => undefined;
  const actions: MockActions = { onChoose: noop, onOpen: noop, onStart: noop, onPause: noop, onResume: noop, onShow: noop, onAnswer: noop, onFlag: noop,
    onClear: noop, onSubmit: noop, onRetryMark: noop, onLeave: noop, ...(onHelp !== undefined ? { onHelp } : {}) };
  return render(<LocaleProvider locale="en"><MockContent view={{ ...EMPTY_MOCKS, status: "ready", ...payload.view, readAt: 0, listedAt: 0 }} now={0} actions={actions}
    subjects={[{ subject: "physics", label: "Physics" }]} names={{ topic: (t) => t, kc: (k) => k }} pastPapers={payload.pastPapers} /></LocaleProvider>);
}

describe("ASM-28 on past papers", () => {
  test("test_asm28_past_paper_help_after_submission_only", () => {
    const asked: [string, string][] = [];
    const marked = placed("mock-sitting.canonical.past-paper", (ref, kind) => asked.push([ref, kind]));
    const chips = marked.container.querySelectorAll("[data-help-chips]");
    expect(chips.length).toBe(3); // one group per question of the marked paper
    fireEvent.click(chips[1]!.querySelector('[data-help-chip="walk_through"]')!);
    expect(asked).toEqual([[expect.stringContaining(":q2"), "walk_through"]]);
    cleanup();
    // The timed sitting shows no help at all (ASM-28: timed papers show no help until submitted).
    const sitting = placed("mock-sitting.canonical.past-paper-question", () => undefined);
    expect(sitting.container.querySelector("[data-help-chips]")).toBeNull();
  });
});

describe("LRN-44", () => {
  test("test_lrn44_home_countdown_plain_words", () => {
    const countdown = { exam_id: `exd_${"0".repeat(26)}`, subject: "physics" as const, name: "Physics paper 2", date: "2027-05-20", time: null, days: 12 };
    const { container } = render(<LocaleProvider locale="en"><ExamCountdownCard countdown={countdown} reminders={[]} onDismiss={() => undefined} /></LocaleProvider>);
    expect(container.textContent).toContain("12 days to Physics paper 2");
    expect(container.querySelector("[data-exam-countdown]")?.getAttribute("data-exam-countdown")).toBe("12");
  });
});
