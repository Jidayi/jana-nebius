import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { StudyContracts as W } from "@jana/client-core";
import { StudyJourney } from "../src/learn/StudyJourney.js";

afterEach(cleanup);
const root = `aid_${"1".repeat(26)}`, cards = `aid_${"2".repeat(26)}`, quiz = `aid_${"3".repeat(26)}`;
const journey: W.StudyJourney = {
  root_aid_id: root, lesson_aid_id: root, cards_aid_id: cards, quiz_aid_id: quiz, next_aid_id: quiz,
  title: "notes.pdf", sources: [{ source_id: `src_${"1".repeat(26)}`, revision: 1 }], phase: "quiz",
  cards_reviewed: 10, cards_total: 10, cards_due: 0, review_card_ids: [], questions_answered: 2, questions_total: 5,
  questions_correct: 0, questions_to_review: 0, retry_quiz: false, next_review_at: null,
};
test("the saved next step shows real progress and uses existing navigation without generating", () => {
  const onContinue = vi.fn(), onLesson = vi.fn(), onResults = vi.fn();
  render(<StudyJourney journey={journey} busy={false} {...{ onContinue, onLesson, onResults }} />);
  expect(screen.getByText("Flashcards: 10 of 10 reviewed · Quiz: 2 of 5 answered")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Continue quiz" }));
  expect(onContinue).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Open lesson" }));
  expect(onLesson).toHaveBeenCalledOnce();
  expect(screen.getByText(/does not change O-level mastery/)).toBeTruthy();
});
test("wrong answers lead to review, then an explicit retry; complete work keeps results and review date", () => {
  const actions = { onContinue: vi.fn(), onLesson: vi.fn(), onResults: vi.fn() };
  const { rerender } = render(<StudyJourney journey={{ ...journey, phase: "review", next_aid_id: root, questions_to_review: 2 }} busy={false} {...actions} />);
  expect(screen.getByText(/2 questions that need another look/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Open quiz" }));
  expect(actions.onResults).toHaveBeenCalledOnce();
  rerender(<StudyJourney journey={{ ...journey, retry_quiz: true }} busy={false} {...actions} />);
  expect(screen.getByRole("button", { name: "Try the quiz again" })).toBeTruthy();
  rerender(<StudyJourney journey={{ ...journey, phase: "complete", questions_answered: 5, questions_correct: 5, next_review_at: 1792886400000 }} busy={true} {...actions} />);
  expect(screen.getByText(/Next flashcard review:/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "View quiz results" }).hasAttribute("disabled")).toBe(true);
});

test("a two-minute review refreshes once when due and cancels on unmount", () => {
  vi.useFakeTimers();
  try {
    vi.setSystemTime(new Date("2026-10-24T12:00:00Z"));
    const onReviewDue = vi.fn();
    const actions = { onContinue: vi.fn(), onLesson: vi.fn(), onResults: vi.fn(), onReviewDue };
    const { unmount, rerender } = render(<StudyJourney journey={{ ...journey, phase: "complete", next_review_at: Date.now() + 120_000 }} busy={false} {...actions} />);
    vi.advanceTimersByTime(119_999);
    expect(onReviewDue).not.toHaveBeenCalled();
    vi.advanceTimersByTime(51);
    expect(onReviewDue).toHaveBeenCalledOnce();
    rerender(<StudyJourney journey={{ ...journey, phase: "complete", next_review_at: Date.now() + 120_000 }} busy={false} {...actions} />);
    unmount();
    vi.advanceTimersByTime(120_050);
    expect(onReviewDue).toHaveBeenCalledOnce();
  } finally { vi.useRealTimers(); }
});
