import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EMPTY_PRACTICE, type PartAnswer, type PracticeItem } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { PracticeContent } from "../src/learn/Practice.js";
import { answerOf, type Draft } from "../src/learn/items.js";
import { draftOf, mockAnswerOf } from "../src/mock/MockExam.js";

afterEach(cleanup);
const inputs: Record<string, PracticeItem["parts"][number]["input"]> = {
  chemical_equation: { kind: "chemical_equation", unbalanced_equation: "H2 + O2 -> H2O", state_symbols_required: true },
  journal_entry: { kind: "journal_entry", currency: "NGN", account_options: [{ id: "cash", label: "Cash" }, { id: "sales", label: "Sales" }] },
  accounting_table: { kind: "accounting_table", currency: "NGN", headers: ["Account", "Amount", "Side"], row_prompts: [] },
  diagram_label: { kind: "diagram_label", diagram_id: "dgm.chm.assessment.v1", target_ids: ["label_1", "label_2"], label_choices: [] },
  short_text: { kind: "short_text", max_characters: 400 },
};
function question(kind: string): PracticeItem {
  return { item_id: "itm.mth.o.number.0901", pack_id: "pack.mth.o", pack_version: "1.0.0", kc_ids: ["kc.mth.o.number.add"],
    kind: kind as PracticeItem["kind"], stem: "Synthetic question", visual: null, marks: 2,
    parts: [{ part_id: "a", prompt: "Give your answer.", uses_parts: [], marks: 2, input: inputs[kind]! }] };
}
function show(kind: string) {
  const onAnswer = vi.fn();
  render(<LocaleProvider locale="en"><PracticeContent view={{ ...EMPTY_PRACTICE, status: "ready", item: question(kind), subject: "mathematics", total: 1, number: 1 }}
    actions={{ onAnswer, onNext: vi.fn(), onEnd: vi.fn() }} /></LocaleProvider>);
  return onAnswer;
}
function enter(name: string, value: string) { fireEvent.change(screen.getByRole("textbox", { name, exact: true }), { target: { value } }); }
function submitted(spy: ReturnType<typeof vi.fn>) { fireEvent.click(screen.getByRole("button", { name: "Check my answer" })); return spy.mock.calls[0]?.[0]; }

test("chemical equations retain coefficients and state symbols through saved mock drafts", () => {
  const onAnswer = show("chemical_equation"); enter("Balanced chemical equation", "2H2(g) + O2(g) -> 2H2O(l)");
  expect(submitted(onAnswer)).toEqual([{ part_id: "a", kind: "chemical_equation", equation: "2H2(g) + O2(g) -> 2H2O(l)" }]);
  expect(screen.getByText(/Include the state symbols/)).toBeTruthy();
});
test("journal entries have named account, side and amount fields and editable rows", () => {
  const onAnswer = show("journal_entry");
  fireEvent.change(screen.getByRole("combobox", { name: "Account" }), { target: { value: "cash" } }); enter("Amount", "200");
  fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
  fireEvent.change(screen.getAllByRole("combobox", { name: "Account" })[1]!, { target: { value: "sales" } });
  fireEvent.change(screen.getAllByRole("combobox", { name: "Side" })[1]!, { target: { value: "credit" } });
  fireEvent.change(screen.getAllByRole("textbox", { name: "Amount" })[1]!, { target: { value: "200" } });
  expect(submitted(onAnswer)).toEqual([{ part_id: "a", kind: "journal_entry", lines: [{ account_id: "cash", side: "debit", amount: "200" }, { account_id: "sales", side: "credit", amount: "200" }] }]);
  fireEvent.click(screen.getByRole("button", { name: "Remove entry 2" })); expect(screen.getAllByRole("combobox", { name: "Account" })).toHaveLength(1);
});
test("accounting rows serialize the authored columns including total rows", () => {
  const onAnswer = show("accounting_table"); enter("Account", "Sales"); enter("Amount", "7"); enter("Side", "total");
  expect(submitted(onAnswer)).toEqual([{ part_id: "a", kind: "accounting_table", rows: [["Sales", "7", "total"]] }]);
  fireEvent.click(screen.getByRole("button", { name: "Add row" })); fireEvent.click(screen.getByRole("button", { name: "Remove row 2" }));
  expect(screen.getAllByRole("textbox")).toHaveLength(3);
});
test("diagram targets accept independent numbered answers", () => {
  const onAnswer = show("diagram_label"); enter("Label 1", "Burette"); enter("Label 2", "Tap");
  expect(submitted(onAnswer)).toEqual([{ part_id: "a", kind: "diagram_label", labels: [{ target_id: "label_1", label: "Burette" }, { target_id: "label_2", label: "Tap" }] }]);
});
test("short answers expose the actual limit and preserve typed text", () => {
  const onAnswer = show("short_text"); enter("Written answer", "  My explanation.\nSecond line.  ");
  expect(screen.getByRole("textbox").getAttribute("maxlength")).toBe("400");
  expect(submitted(onAnswer)).toEqual([{ part_id: "a", kind: "short_text", text: "  My explanation.\nSecond line.  " }]);
});
test.each(Object.keys(inputs))("%s partial drafts round trip through mocks without losing fields", (kind) => {
  const q = question(kind);
  const drafts: Record<string, Draft> = { chemical_equation: { value: "H2 ->" }, short_text: { value: "half a thought" },
    journal_entry: { lines: [{ account_id: "cash", side: "credit", amount: "" }] }, accounting_table: { rows: [["cash", "", ""]] },
    diagram_label: { labels: { label_1: "Burette" } } };
  const a = answerOf(q.parts[0]!, drafts[kind]!) as PartAnswer;
  expect(a).not.toBeNull();
  const saved = mockAnswerOf(q, { a: draftOf(a) }, {});
  expect(saved).toEqual({ parts: [a] });
});
