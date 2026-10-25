// UXS-55 (D103): a new tutor line is written on as presentation only: with reduced motion it is whole on arrival; during
// a write-on it can be selected and its "Why?" opened; a screen reader gets the whole line once, never word by word.
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { StepRec } from "@jana/client-core";
import { Board, BoardStep } from "../src/board/Board.js";
import { VisualSettingsProvider } from "../src/visuals/VisualViewer.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => cleanup());

const BOARD = `brd_${"4".repeat(26)}`;
const OLD = `stp_${"1".repeat(26)}`;
const NEW = `stp_${"2".repeat(26)}`;

function line(f: Fixture, stepId: string, index: number, latex: string) {
  f.emit({ type: "board.step", board_id: BOARD, step_id: stepId, index, latex, reason: null, owner: "tutor", status: "final", check_id: null, error: null }, null);
}

function board(reducedMotion: boolean) {
  const f = new Fixture();
  f.startTurn();
  line(f, OLD, 0, "2x - 3 = 7");
  f.render(<VisualSettingsProvider settings={{ reducedMotion, textScale: 1 }}><Board sessionId={SESSION} /></VisualSettingsProvider>);
  line(f, NEW, 1, "2x = 10");
  return f;
}

const row = (id: string) => document.querySelector(`[data-step-id="${id}"]`) as HTMLElement;

describe("UXS-55", () => {
  test("uxs55_reduced_motion_instant", () => {
    board(true);
    // Reduced motion: the new line is whole on arrival.
    expect(row(NEW).querySelector("[data-write-on]")).toBeNull();
    cleanup();
    board(false);
    // Otherwise it is written on at a reading pace (40 ms a character, at most 1.2 s); the line already there is not.
    const mask = row(NEW).querySelector("[data-write-on]") as HTMLElement;
    expect(mask.getAttribute("data-write-on")).toBe("paced");
    expect(Number(mask.getAttribute("data-write-on-ms"))).toBe(Math.min(1200, 40 * "2x = 10".length));
    expect(row(OLD).querySelector("[data-write-on]")).toBeNull();
    // During the write-on the line can be selected (the mask never takes a pointer)...
    expect(mask.className).toContain("pointer-events-none");
    fireEvent.click(row(NEW));
    expect(row(NEW).getAttribute("data-selected")).toBe("true");
    cleanup();
    // ...and its "Why?" opened.
    const onWhy = vi.fn();
    const step: StepRec = { step_id: NEW, index: 1, latex: "2x = 10", reason: null, owner: "tutor", status: "final", check_id: null, error: null };
    new Fixture().render(<ol><BoardStep step={step} number={2} current writeOn={0.3} onWhy={onWhy} /></ol>);
    fireEvent.click(screen.getByRole("button", { name: "Ask why step 2 works" }));
    expect(onWhy).toHaveBeenCalledWith(NEW);
  });

  test("uxs55_screen_reader_parity", () => {
    board(false);
    const written = row(NEW);
    // The whole line is in the row's name from its arrival; the reveal is hidden from assistive technology and no live
    // region inside the line updates with it.
    expect(written.getAttribute("aria-label")).toContain("2x = 10");
    expect(written.querySelector("[data-write-on]")?.getAttribute("aria-hidden")).toBe("true");
    expect(written.querySelector("[aria-live], [role='status']")).toBeNull();
  });
});
