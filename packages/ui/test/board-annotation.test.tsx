// VSL-40 (D103): the tutor's annotation is drawn on the line it targets by id, never over the student's writing, keeps
// its word in greyscale, is announced in words, is replaced by the next one and cleared by a new line.
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { Board } from "../src/board/Board.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => cleanup());

const BOARD = `brd_${"8".repeat(26)}`;
const STUDENT = `stp_${"1".repeat(26)}`;
const TUTOR = `stp_${"2".repeat(26)}`;
const ANN = (n: number) => `ann_${String(n).repeat(26)}`;

function line(f: Fixture, stepId: string, index: number, latex: string, owner: string, terms: { term_id: string; start: number; end: number }[]) {
  f.emit({ type: "board.step", board_id: BOARD, step_id: stepId, index, latex, reason: null, owner, status: "final", check_id: null, error: null, terms }, null);
}

function annotate(f: Fixture, n: number, mark: string, stepId: string, terms: string | null) {
  f.emit({ type: "board.annotate", board_id: BOARD, annotation_id: ANN(n), mark, target: { step_id: stepId, terms, visual_id: null, part_id: null }, to: null, note: null }, null);
}

describe("VSL-40", () => {
  test("vsl40_student_line_not_hidden", () => {
    const f = new Fixture();
    f.startTurn();
    line(f, TUTOR, 0, "2x + 3 = 11", "tutor", [{ term_id: "t1", start: 0, end: 2 }, { term_id: "t2", start: 5, end: 6 }, { term_id: "t3", start: 9, end: 11 }]);
    line(f, STUDENT, 1, "2x = 14", "student", [{ term_id: "t1", start: 0, end: 2 }, { term_id: "t2", start: 5, end: 7 }]);
    annotate(f, 1, "circle", STUDENT, "t2");
    f.render(<Board sessionId={SESSION} />);
    const row = document.querySelector(`[data-step-id="${STUDENT}"]`) as HTMLElement;
    const mark = row.querySelector("[data-annotation]") as HTMLElement;
    // The mark is a separate element after the writing, drawn unfilled and hidden from assistive technology; the
    // student's line itself is untouched, every character still there.
    expect(mark.getAttribute("data-annotation")).toBe("circle");
    const writing = row.querySelector(".board-math") as HTMLElement;
    expect(writing.contains(mark)).toBe(false);
    expect(writing.textContent).toContain("14");
    expect(row.querySelector("[data-annotation-mark]")?.getAttribute("aria-hidden")).toBe("true");
    expect(row.querySelector("ellipse")?.getAttribute("fill")).toBe("none");
    // In greyscale the mark keeps its word: "Look here" on the student's line, in words, with the term it points at.
    const word = row.querySelector("[data-annotation-word]") as HTMLElement;
    expect(word.textContent).toBe("Look here14");
    expect(screen.getByRole("status").textContent).toBe("Look here: 14");
    // A strike is never drawn through the student's writing; the tutor's own line can be struck.
    annotate(f, 2, "strike", STUDENT, "t1");
    expect(document.querySelector(`[data-step-id="${STUDENT}"] path`)).toBeNull();
    annotate(f, 3, "strike", TUTOR, "t2");
    const tutorRow = document.querySelector(`[data-step-id="${TUTOR}"]`) as HTMLElement;
    expect(tutorRow.querySelector("[data-annotation]")?.getAttribute("data-annotation-target")).toBe("t2");
    // One annotation at a time: the student's line lost its mark when the tutor's line got one.
    expect(row.querySelector("[data-annotation]")).toBeNull();
    // A new board line clears it.
    line(f, `stp_${"3".repeat(26)}`, 2, "x = 7", "tutor", []);
    expect(document.querySelector("[data-annotation]")).toBeNull();
  });
});
