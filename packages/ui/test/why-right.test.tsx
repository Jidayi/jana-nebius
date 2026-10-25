// UXS-62 (D103): "Why is this right?" is offered on a practice item only once it is marked correct, never after a
// wrong answer (where "Help me" applies).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { EMPTY_PRACTICE, type PracticeItem, type PracticeMarked } from "@jana/client-core";
import { LocaleProvider } from "../src/i18n.js";
import { PracticeContent } from "../src/learn/Practice.js";

afterEach(cleanup);

const ITEM: PracticeItem = {
  item_id: "itm.mth.o.number.0001", pack_id: "pack.mth.o", pack_version: "1.0.0", kc_ids: ["kc.mth.o.number.add"],
  kind: "numeric", stem: "Synthetic: 2 + 3.", visual: null, marks: 1,
  parts: [{ part_id: "a", prompt: "Give your answer.", uses_parts: [], marks: 1, input: { kind: "numeric" } }],
} as PracticeItem;

function marked(verdict: PracticeMarked["verdict"]): PracticeMarked {
  return { attempt_id: `att_${"1".repeat(26)}`, verdict, marks_awarded: verdict === "correct" ? 1 : 0, marks_total: 1, feedback_key: "",
    first_error: null, mastery_change: { kc_id: "kc.mth.o.number.add", band_before: "learning", band_after: "learning" }, next_item: null } as unknown as PracticeMarked;
}

function view(verdict: PracticeMarked["verdict"]) {
  return { ...EMPTY_PRACTICE, status: "ready" as const, item: ITEM, subject: "mathematics", total: 1, number: 1, closed: verdict === "correct",
    tries: [{ answers: [], marked: marked(verdict) }] };
}

test("test_uxs62_offered_only_after_a_correct_mark", () => {
  const onWhyRight = vi.fn();
  const actions = { onAnswer: vi.fn(), onNext: vi.fn(), onEnd: vi.fn(), onWhyRight };
  const { rerender } = render(<LocaleProvider locale="en"><PracticeContent view={view("incorrect")} actions={actions} /></LocaleProvider>);
  expect(screen.queryByRole("button", { name: "Why is this right?" })).toBeNull();
  rerender(<LocaleProvider locale="en"><PracticeContent view={view("correct")} actions={actions} /></LocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Why is this right?" }));
  expect(onWhyRight).toHaveBeenCalledTimes(1);
});
