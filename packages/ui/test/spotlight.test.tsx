// UXS-57 (D103): a spotlight dims every board line and visual part other than the target to the configured opacity,
// keeps the target's ring and underline (never colour alone), and restores at the next utterance or student action.
import { cleanup, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { CLIENT_KEYS } from "@jana/client-core";
import { Board } from "../src/board/Board.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => cleanup());

const BOARD = `brd_${"9".repeat(26)}`;
const STEPS = [1, 2, 3].map((i) => `stp_${String(i).repeat(26)}`);

function board(f: Fixture) {
  STEPS.forEach((stepId, i) => f.emit({ type: "board.step", board_id: BOARD, step_id: stepId, index: i, latex: `x = ${i + 1}`, reason: null, owner: "tutor", status: "final", check_id: null, error: null }, null));
}

function spotlight(f: Fixture, stepId: string) {
  f.emit({ type: "board.highlight", board_id: BOARD, step_ids: [stepId], ttl_ms: null, spotlight: true }, null);
}

const dimmed = () => [...document.querySelectorAll("[data-step-id]")].filter((el) => el.getAttribute("data-dimmed") === "true").map((el) => el.getAttribute("data-step-id"));

describe("UXS-57", () => {
  test("uxs57_spotlight_dims_and_restores", () => {
    const f = new Fixture();
    f.startTurn();
    board(f);
    f.render(<Board sessionId={SESSION} />);
    spotlight(f, STEPS[1]!);
    expect(dimmed()).toEqual([STEPS[0], STEPS[2]]);
    const other = document.querySelector(`[data-step-id="${STEPS[0]}"]`) as HTMLElement;
    expect(other.style.opacity).toBe(String(CLIENT_KEYS.board_spotlight_dim_opacity));
    // The next utterance restores it.
    f.text("Now look at the second line.");
    expect(dimmed()).toEqual([]);
    // So does any student action on the board.
    spotlight(f, STEPS[2]!);
    expect(dimmed()).toEqual([STEPS[0], STEPS[1]]);
    fireEvent.keyDown(document.querySelector(`[data-step-id="${STEPS[0]}"]`) as HTMLElement, { key: "ArrowDown" });
    expect(dimmed()).toEqual([]);
    // Visual parts are dimmed the same way (packages/renderers/test/build.test.tsx, test_uxs57_visual_parts_dimmed).
  });

  test("uxs57_spotlight_not_colour_alone", () => {
    const f = new Fixture();
    f.startTurn();
    board(f);
    f.render(<Board sessionId={SESSION} />);
    spotlight(f, STEPS[1]!);
    const target = document.querySelector(`[data-step-id="${STEPS[1]}"]`) as HTMLElement;
    // In greyscale the target keeps its ring (the pointer outline), its underline and its name in words.
    expect(target.className).toContain("jana-pointer");
    expect(target.querySelector(".board-math")?.className).toContain("underline");
    expect(target.getAttribute("aria-label")).toContain("Showing");
    expect(target.getAttribute("data-dimmed")).toBeNull();
  });
});
