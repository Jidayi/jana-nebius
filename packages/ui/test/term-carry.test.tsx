// UXS-61 (D103): a new line's verified term moves are played once, exactly as the engine sent them (a carried term
// travels by transform, a cancelled one is struck through); with reduced motion or in low-power mode nothing moves and
// the new line shows at once.
import { act, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { Board } from "../src/board/Board.js";
import { TERM_CARRY_MS } from "../src/board/TermCarry.js";
import { VisualSettingsProvider } from "../src/visuals/VisualViewer.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => { cleanup(); vi.useRealTimers(); });

const BOARD = `brd_${"6".repeat(26)}`;
const OLD = `stp_${"1".repeat(26)}`;
const NEW = `stp_${"2".repeat(26)}`;
const MOVES = [{ from: `${OLD}.t2`, to: "t3", kind: "carry" }, { from: `${OLD}.t4`, to: null, kind: "cancel" }];

function line(f: Fixture, stepId: string, index: number, latex: string, terms: [number, number][], moves?: unknown[]) {
  f.emit({ type: "board.step", board_id: BOARD, step_id: stepId, index, latex, reason: null, owner: "student", status: "correct",
    check_id: null, error: null, terms: terms.map(([start, end], i) => ({ term_id: `t${i + 1}`, start, end })),
    ...(moves === undefined ? {} : { term_moves: moves }) }, null);
}

function board(settings: { reducedMotion: boolean; lowPower?: boolean }) {
  const f = new Fixture();
  f.startTurn();
  line(f, OLD, 0, "2x - 3 = 7 + y - y", [[0, 2], [3, 6], [9, 10], [11, 14], [15, 18]]);
  f.render(<VisualSettingsProvider settings={{ textScale: 1, ...settings }}><Board sessionId={SESSION} /></VisualSettingsProvider>);
  act(() => line(f, NEW, 1, "2x = 7 + 3", [[0, 2], [5, 6], [7, 10]], MOVES));
  return f;
}

const moving = () => [...document.querySelectorAll<HTMLElement>("[data-term-move]")];

describe("UXS-61", () => {
  test("test_uxs61_carry_plays_the_engine_moves_only", () => {
    vi.useFakeTimers();
    board({ reducedMotion: false });
    act(() => { vi.advanceTimersByTime(16); });
    // Exactly the moves the engine sent, each from its term of the line before, and nothing else moves.
    expect(moving().map((m) => [m.getAttribute("data-from"), m.getAttribute("data-to"), m.getAttribute("data-term-move")]))
      .toEqual([[`${OLD}.t2`, "t3", "carry"], [`${OLD}.t4`, "", "cancel"]]);
    expect(moving().every((m) => m.getAttribute("aria-hidden") === "true" && m.style.transform.startsWith("translate("))).toBe(true);
    expect(moving()[1]?.className).toContain("line-through");
    // Played once: the moves are gone when the line settles, and the new line reads as usual.
    act(() => { vi.advanceTimersByTime(TERM_CARRY_MS + 200); });
    expect(moving()).toEqual([]);
    expect(document.querySelector(`[data-step-id="${NEW}"]`)?.getAttribute("aria-label")).toContain("2x = 7 + 3");
  });

  test("uxs61_reduced_motion_skips", () => {
    board({ reducedMotion: true });
    expect(moving()).toEqual([]);
    expect(document.querySelector(`[data-step-id="${NEW}"]`)).not.toBeNull();
    cleanup();
    board({ reducedMotion: false, lowPower: true });
    expect(moving()).toEqual([]);
  });
});
