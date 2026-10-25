import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { LearningJourneyView } from "@jana/client-core";
import { LearningJourney } from "../src/learn/LearningJourney.js";

afterEach(cleanup);
const view: LearningJourneyView = {
  goal: { node_id: "cur.phy.o.forces", kc_id: "kc.phy.o.forces.force", title: "Forces", objective: "Calculate a force", subject: "physics" },
  source: { source_id: `src_${"1".repeat(26)}`, revision: 1 }, source_changed: true,
  phase: "repair", evidence: "incorrect", prior_attempts: 1, practice_set_id: "set_saved",
  lesson_id: "les.phy.o.forces", lesson_opened: false, stage: "starting",
};
const props = () => ({ onStep: vi.fn(), onSource: vi.fn(), onTopic: vi.fn(), onRetry: vi.fn(), busy: false, error: false });

test("incorrect evidence stays uncertain and uses the existing lesson with a pinned source return", () => {
  const actions = props(); render(<LearningJourney {...actions} view={view} />);
  expect(screen.getByText(/That alone does not explain why/)).toBeTruthy();
  expect(screen.getByText(/still uses the saved revision/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Review the relevant lesson" }));
  expect(actions.onStep).toHaveBeenCalledWith("review");
  fireEvent.click(screen.getByRole("button", { name: "Back to material · revision 1" }));
  expect(actions.onSource).toHaveBeenCalledOnce();
});

test("independent success does not claim mastery and unavailable checks remain recoverable", () => {
  const actions = props(); const { rerender } = render(<LearningJourney {...actions} view={{ ...view, phase: "complete", evidence: "independent_correct" }} />);
  expect(screen.getByText(/formal mastery still follows/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Continue adaptive practice" })).toBeTruthy();
  rerender(<LearningJourney {...actions} view={{ ...view, phase: "unavailable" }} />);
  fireEvent.click(screen.getByRole("button", { name: "Check for an eligible question" }));
  expect(actions.onStep).toHaveBeenCalledWith("check");
});

test("teaching starts the existing lesson without forcing a question or discarding saved attempts", () => {
  const actions = props();
  const ready = { ...view, phase: "ready" as const, evidence: "none" as const, practice_set_id: null };
  const { rerender } = render(<LearningJourney {...actions} view={ready} />);
  expect(screen.getByText(/saved lesson position and previous attempts are kept/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Teach me from the beginning" }));
  expect(actions.onStep).toHaveBeenCalledWith("review");
  expect(actions.onStep).not.toHaveBeenCalledWith("practice");
  rerender(<LearningJourney {...actions} view={{ ...ready, lesson_opened: true }} />);
  expect(screen.getByRole("button", { name: "Continue the lesson" })).toBeTruthy();
  rerender(<LearningJourney {...actions} view={{ ...ready, lesson_id: null }} />);
  expect(screen.queryByRole("button", { name: "Teach me from the beginning" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Check my starting point" }));
  expect(actions.onStep).toHaveBeenCalledWith("practice");
});

test("lesson and tutor navigation show the current step and explicit return actions", () => {
  const actions = { ...props(), onPlan: vi.fn() };
  const ready = { ...view, phase: "ready" as const, lesson_opened: true };
  const { rerender } = render(<LearningJourney {...actions} view={ready} place="lesson" />);
  expect(screen.getByRole("list", { name: "Learning journey steps" }).querySelector('[aria-current="step"]')?.textContent).toContain("Learn");
  fireEvent.click(screen.getByRole("button", { name: "Try a question" }));
  expect(actions.onStep).toHaveBeenCalledWith("practice");
  fireEvent.click(screen.getByRole("button", { name: "Back to daily plan" }));
  expect(actions.onPlan).toHaveBeenCalledOnce();
  rerender(<LearningJourney {...actions} view={view} place="tutor" />);
  expect(screen.getByRole("list", { name: "Learning journey steps" }).querySelector('[aria-current="step"]')?.textContent).toContain("Practise");
  fireEvent.click(screen.getByRole("button", { name: "Back to your question" }));
  expect(actions.onStep).toHaveBeenLastCalledWith("practice");
  fireEvent.click(screen.getByRole("button", { name: "Back to lesson" }));
  expect(actions.onStep).toHaveBeenLastCalledWith("review");
});

test("a missing lesson offers tutor help without claiming progress", () => {
  const actions = { ...props(), onHelp: vi.fn() };
  render(<LearningJourney {...actions} view={{ ...view, lesson_id: null }} />);
  fireEvent.click(screen.getByRole("button", { name: "Get help with this question" }));
  expect(actions.onHelp).toHaveBeenCalledOnce();
  expect(actions.onStep).not.toHaveBeenCalled();
});
