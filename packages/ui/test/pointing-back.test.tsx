// UXS-58 (D103): terms can be selected and asked about by keyboard alone, the screen reader names the selected term,
// and "Why this?" names exactly the selected range (`stp_….t1-t2`); the selection is reported so "this" refers to it.
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import type { StepRec } from "@jana/client-core";
import { BoardStep } from "../src/board/Board.js";
import { Fixture } from "./harness.js";

afterEach(() => cleanup());

const STEP: StepRec = {
  step_id: `stp_${"5".repeat(26)}`, index: 0, latex: "2x - 3 = 7", reason: null, owner: "tutor", status: "final", check_id: null, error: null,
  terms: [{ term_id: "t1", start: 0, end: 2 }, { term_id: "t2", start: 3, end: 6 }, { term_id: "t3", start: 9, end: 10 }],
};

describe("UXS-58", () => {
  test("uxs58_keyboard_term_selection", () => {
    const f = new Fixture();
    const asked: string[] = [];
    const reported: (string | null)[] = [];
    f.render(<ol><BoardStep step={STEP} number={1} current={false} onWhy={(ref) => asked.push(ref)} onTermSelect={(ref) => reported.push(ref)} /></ol>);
    const line = document.querySelector(`[data-step-id="${STEP.step_id}"]`) as HTMLElement;
    line.focus();
    // Right selects the first term, again the second; the selection is named in words.
    fireEvent.keyDown(line, { key: "ArrowRight" });
    expect(screen.getByRole("status").textContent).toBe("Selected: 2x");
    fireEvent.keyDown(line, { key: "ArrowRight" });
    expect(screen.getByRole("status").textContent).toBe("Selected: - 3");
    // Shift extends the range back to the first term.
    fireEvent.keyDown(line, { key: "ArrowLeft", shiftKey: true });
    expect(document.querySelector("[data-term-selection]")?.getAttribute("data-term-selection")).toBe("t1-t2");
    expect(screen.getByRole("status").textContent).toBe("Selected: 2x - 3");
    expect(reported).toEqual([`${STEP.step_id}.t1`, `${STEP.step_id}.t2`, `${STEP.step_id}.t1-t2`]);
    // "Why this?" is reached by keyboard and names exactly that range.
    const why = screen.getByRole("button", { name: "Why this?" });
    why.focus();
    fireEvent.click(why);
    expect(asked).toEqual([`${STEP.step_id}.t1-t2`]);
    // Escape clears the selection and reports it cleared.
    fireEvent.keyDown(line, { key: "Escape" });
    expect(document.querySelector("[data-term-selection]")).toBeNull();
    expect(reported.at(-1)).toBeNull();
  });
});
