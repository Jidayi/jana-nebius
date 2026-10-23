import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EMPTY_SAVED_QUESTIONS, type SavedQuestionsView } from "@jana/client-core";
import { SAVED } from "../../client-core/test/savedcore.js";
import { SavedQuestionsContent } from "../src/learn/SavedQuestions.js";

afterEach(cleanup);
function show(flags: Partial<SavedQuestionsView> = {}) {
  const actions = { onSelect: vi.fn(), onStatus: vi.fn(), onRemove: vi.fn(), onRetry: vi.fn(), onClose: vi.fn(), onPrint: vi.fn() };
  render(<SavedQuestionsContent view={{ ...EMPTY_SAVED_QUESTIONS, status: "ready", questions: [SAVED], ...flags }} subject={() => "Physics"} topic={() => "Motion"} actions={actions} />);
  return actions;
}
test("uxs42_saved_question_snapshot", () => {
  const actions = show({ selected: SAVED.question_id });
  expect(screen.getByText(SAVED.snapshot.problem)).toBeTruthy();
  expect(screen.getByText("Divide distance by time")).toBeTruthy();
  expect(screen.getByText("You saved this question for later.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /send|recipient|share|sync/i })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Mark resolved" })); expect(actions.onStatus).toHaveBeenCalledWith(SAVED.question_id, "sorted");
  fireEvent.click(screen.getByRole("button", { name: "Print question" })); expect(actions.onPrint).toHaveBeenCalledOnce();
});
test("list opens the pinned question and searches locally", () => {
  const actions = show(); fireEvent.change(screen.getByRole("searchbox"), { target: { value: "unmatched" } });
  expect(screen.getByText("No saved question matches your search.")).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "cyclist" } });
  fireEvent.click(screen.getByRole("button", { name: SAVED.snapshot.problem })); expect(actions.onSelect).toHaveBeenCalledWith(SAVED.question_id);
});
test("removal requires a confirmation and cancellation keeps the question", () => {
  const actions = show({ selected: SAVED.question_id });
  fireEvent.click(screen.getByRole("button", { name: "Remove saved question" }));
  const dialog = screen.getByRole("alertdialog"); fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(actions.onRemove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Remove saved question" }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove saved question" }));
  expect(actions.onRemove).toHaveBeenCalledWith(SAVED.question_id);
});
