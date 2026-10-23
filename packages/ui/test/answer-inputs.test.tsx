import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EMPTY_MOCKS, EMPTY_PRACTICE, type MockView, type PracticeItem } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { PracticeContent } from "../src/learn/Practice.js";
import { answerOf } from "../src/learn/items.js";
import { MockContent, draftOf, mockAnswerOf, type MockActions } from "../src/mock/MockExam.js";
import { STATES } from "../gallery/index.js";

afterEach(cleanup);

const item = (kind: "algebraic" | "equation_solutions"): PracticeItem => ({
  item_id: "itm.mth.o.algebra_and_graphs.0901", pack_id: "pack.mth.o", pack_version: "1.0.0",
  kc_ids: ["kc.mth.o.algebra_and_graphs.expand_brackets"], kind, stem: "Synthetic algebra question.", visual: null, marks: 2,
  parts: [{ part_id: "a", prompt: "Give your answer.", uses_parts: [], marks: 2,
    input: kind === "algebraic" ? { kind, variables: ["x"] } : { kind, variable: "x" } }],
});

test.each([
  ["algebraic", "x^2 - 2*x - 8", { part_id: "a", kind: "algebraic", latex: "x^2 - 2*x - 8" }],
  ["equation_solutions", "2, -3, 1/2", { part_id: "a", kind: "equation_solutions", values: ["2", "-3", "1/2"] }],
] as const)("%s answers can be entered in practice and restored in a mock", (kind, text, expected) => {
  const question = item(kind), onAnswer = vi.fn();
  render(<LocaleProvider locale="en"><PracticeContent
    view={{ ...EMPTY_PRACTICE, status: "ready", item: question, subject: "mathematics", total: 1, number: 1 }}
    actions={{ onAnswer, onNext: vi.fn(), onEnd: vi.fn() }} /></LocaleProvider>);
  const field = screen.getByRole("textbox", { name: "Your answer" });
  fireEvent.change(field, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Check my answer" }));
  expect(onAnswer.mock.calls[0]?.[0]).toEqual([expected]);
  const answer = answerOf(question.parts[0]!, { value: text })!;
  const restored = draftOf(answer);
  expect(restored.value).toBe(text);
  expect(mockAnswerOf(question, { a: restored }, { a: "x + 3 = 5" })).toEqual({
    parts: [expected], working: [{ part_id: "a", latex: "x + 3 = 5" }],
  });
});

test("solution entry rejects an empty value and incomplete comma-separated lists", () => {
  const part = item("equation_solutions").parts[0]!;
  for (const value of ["", " ", "2,", ",2", "2,,3"]) expect(answerOf(part, { value })).toBeNull();
});

test("retrying a failed mock save does not submit the paper", () => {
  const payload = STATES.find((s) => s.id === "mock-sitting.error-retriable.save-failed")!.payload as { view: Partial<MockView> };
  const actions: MockActions = { onChoose: vi.fn(), onOpen: vi.fn(), onStart: vi.fn(), onPause: vi.fn(), onResume: vi.fn(), onShow: vi.fn(),
    onAnswer: vi.fn(), onFlag: vi.fn(), onClear: vi.fn(), onSubmit: vi.fn(), onRetryMark: vi.fn(), onRetrySave: vi.fn(), onLeave: vi.fn() };
  render(<LocaleProvider locale="en"><MockContent view={{ ...EMPTY_MOCKS, status: "ready", ...payload.view }} now={0}
    actions={actions} subjects={[]} names={{ topic: () => null, kc: () => null }} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(actions.onRetrySave).toHaveBeenCalledOnce(); expect(actions.onSubmit).not.toHaveBeenCalled();
});
