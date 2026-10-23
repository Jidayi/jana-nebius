// M43.f on the board and visuals: the three kinds of highlight stay distinct in shape and in words (UXS-63), the
// tutor's spoken pointer reaches a board line or a diagram part only by id (VSL-45), and it is announced for a screen
// reader; the ring is static under reduced motion (TABLE DSN-10a).
import { readFileSync } from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import type { PointerView, SpeechController } from "@jana/client-core";
import { Board } from "../src/board/Board.js";
import { SpeechToolsProvider } from "../src/voice/SpeechTools.js";
import { VisualViewer, type VisualHooks, type VisualSpec } from "../src/visuals/VisualViewer.js";
import { Fixture, SESSION } from "./harness.js";

afterEach(() => cleanup());

const BOARD = `brd_${"7".repeat(26)}`;
const LINE = `stp_${"1".padStart(26, "0")}`;
const NEXT = `stp_${"2".padStart(26, "0")}`;

/** The session's voice as the board sees it: only the pointer the controller fired from heard playback. */
function voice(pointer: PointerView | null) {
  const listeners = new Set<() => void>();
  let view = { pointer };
  const controller = { voice: { subscribe: (l: () => void) => { listeners.add(l); return () => listeners.delete(l); }, getState: () => view } };
  return {
    controller: controller as unknown as SpeechController,
    point(next: PointerView | null) { act(() => { view = { pointer: next }; for (const l of listeners) l(); }); },
  };
}
const at = (stepId: string): PointerView => ({ target: { kind: "step", step_id: stepId }, fired_ms: 300, word_ms: 300, timing: "estimated" });

function line(f: Fixture, stepId: string, index: number, latex: string, status = "final", owner = "tutor", reason: string | null = null) {
  f.emit({ type: "board.step", board_id: BOARD, step_id: stepId, index, latex, reason, owner, status, check_id: status === "final" ? "chk_step2" : null, error: null }, null);
}

describe("UXS-63", () => {
  test("uxs63_highlight_kinds_distinct", () => {
    const f = new Fixture();
    line(f, LINE, 0, "2x + 3 = 11", "awaiting", "student");
    f.emit({ type: "board.await", board_id: BOARD, step_id: LINE, prompt: "Your turn", input_kind: "latex" }, null);
    const v = voice(null);
    f.render(<SpeechToolsProvider controller={v.controller}><Board sessionId={SESSION} /></SpeechToolsProvider>);
    v.point(at(LINE));
    const row = document.querySelector<HTMLElement>(`li[data-step-id="${LINE}"]`);
    if (row === null) throw new Error("no row");
    fireEvent.click(row);
    // All three on one line: each its own shape, none hiding another, each named in words.
    expect(row.dataset.current).toBe("true");
    expect(row.dataset.highlighted).toBe("true");
    expect(row.dataset.selected).toBe("true");
    expect(row.className).toContain("bg-board-current"); // the wash and the accent rule
    expect(row.className).toContain("jana-pointer"); // the solid ring
    expect(row.className).toContain("jana-selected"); // the dashed outline
    expect(row.getAttribute("aria-current")).toBe("step"); // read as "current step"
    expect(row.getAttribute("aria-label")).toMatch(/, Showing, Selected$/);
    // The shapes, as the stylesheet draws them: a solid inset ring and a dashed outline outside the line.
    const css = readFileSync(path.join(import.meta.dirname, "../src/primitives/motion.css"), "utf8");
    expect(css).toMatch(/\.jana-pointer\s*{[^}]*box-shadow: inset 0 0 0 2px/);
    expect(css).toMatch(/\.jana-selected\s*{[^}]*outline: 2px dashed/);
  });

  test("uxs63_cleanup_on_interrupt_and_revision", () => {
    const f = new Fixture();
    line(f, LINE, 0, "2x + 3 = 11");
    line(f, NEXT, 1, "2x + 3 - 3 = 11 - 3");
    const v = voice(at(NEXT));
    f.render(<SpeechToolsProvider controller={v.controller}><Board sessionId={SESSION} /></SpeechToolsProvider>);
    const row = (id: string) => document.querySelector<HTMLElement>(`li[data-step-id="${id}"]`);
    expect(row(NEXT)?.dataset.highlighted).toBe("true");
    v.point(null); // the controller cleared its pointer (interruption, flush, session change: see client-core)
    expect(row(NEXT)?.dataset.highlighted).toBeUndefined();
    const first = row(LINE);
    if (first === null) throw new Error("no row");
    fireEvent.click(first);
    expect(row(LINE)?.dataset.selected).toBe("true");
    line(f, LINE, 0, "2x + 3 = 12"); // the selected line is revised: the selection clears
    expect(row(LINE)?.dataset.selected).toBeUndefined();
  });

  test("test_uxs63_keyboard_selects_a_line", () => {
    // Keyboard alone (LOC-12): Enter on a focused line selects it, and the selection is named in words.
    const f = new Fixture();
    line(f, LINE, 0, "2x + 3 = 11");
    const v = voice(null);
    f.render(<SpeechToolsProvider controller={v.controller}><Board sessionId={SESSION} /></SpeechToolsProvider>);
    const row = document.querySelector<HTMLElement>(`li[data-step-id="${LINE}"]`);
    if (row === null) throw new Error("no row");
    row.focus();
    fireEvent.keyDown(row, { key: "Enter" });
    expect(row.dataset.selected).toBe("true");
    expect(row.getAttribute("aria-label")).toMatch(/, Selected$/);
  });

  test("test_uxs63_pointer_ring_static_under_reduced_motion", () => {
    const css = readFileSync(path.join(import.meta.dirname, "../src/primitives/motion.css"), "utf8");
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/\.jana-pointer\s*{\s*transition: none;/);
    expect(css).toMatch(/\[data-reduced-motion="true"\] \.jana-pointer\s*{\s*transition: none;/);
  });
});

describe("UXS-64 and VSL-45", () => {
  test("test_uxs64_board_announces_the_demonstration_in_words", () => {
    const f = new Fixture();
    line(f, LINE, 0, "2x + 3 = 11");
    line(f, NEXT, 1, "2x + 3 - 3 = 11 - 3", "final", "tutor", "take 3 from both sides");
    const v = voice(null);
    f.render(<SpeechToolsProvider controller={v.controller}><Board sessionId={SESSION} /></SpeechToolsProvider>);
    // With sound off the demonstration is all there in text: the line, its reason and its check.
    expect(screen.getByText("take 3 from both sides")).toBeTruthy();
    const live = document.querySelector('[data-board-showing=""]');
    expect(live?.getAttribute("aria-live")).toBe("polite");
    expect(live?.textContent).toBe("");
    v.point(at(NEXT));
    expect(live?.textContent).toBe("Showing: step 2");
  });

  test("test_uxs64_the_same_pointer_on_a_labelled_diagram", () => {
    // The physics pack's refraction drawing (its renderer fixture): a cue on `refracted_ray` rings that part and is
    // announced by name; a cue on a part the drawing does not have draws nothing (VSL-45).
    const fixture = JSON.parse(readFileSync(path.join(import.meta.dirname, "../../renderers/fixtures/visuals/library-refraction.json"), "utf8")) as { spec: VisualSpec };
    const spec = fixture.spec;
    const seen: string[][] = [];
    const hooks: VisualHooks = {
      check: () => [], labelModes: ["shown"],
      View: ({ focus }) => { seen.push(focus); return <svg data-focus={focus.join(" ")} />; },
      Fallback: () => <p>fallback</p>,
    };
    const f = new Fixture();
    const v = voice(null);
    f.render(<SpeechToolsProvider controller={v.controller}><VisualViewer spec={spec} hooks={hooks} /></SpeechToolsProvider>);
    v.point({ target: { kind: "part", visual_id: spec.visual_id, part_id: "refracted_ray" }, fired_ms: 0, word_ms: 0, timing: "estimated" });
    expect(seen[seen.length - 1]).toEqual(["refracted_ray"]);
    expect(screen.getByText("Showing: Refracted ray")).toBeTruthy();
    v.point({ target: { kind: "part", visual_id: spec.visual_id, part_id: "mirror" }, fired_ms: 0, word_ms: 0, timing: "estimated" });
    expect(seen[seen.length - 1]).toEqual([]);
    v.point({ target: { kind: "part", visual_id: "vis_01JZ0000000000000000000009", part_id: "refracted_ray" }, fired_ms: 0, word_ms: 0, timing: "estimated" });
    expect(seen[seen.length - 1]).toEqual([]);
  });

  test("test_vsl45_a_pointer_at_a_line_not_on_the_board_draws_nothing", () => {
    const f = new Fixture();
    line(f, LINE, 0, "2x + 3 = 11");
    const v = voice(at(`stp_${"9".padStart(26, "0")}`));
    f.render(<SpeechToolsProvider controller={v.controller}><Board sessionId={SESSION} /></SpeechToolsProvider>);
    expect(document.querySelectorAll('li[data-highlighted="true"]').length).toBe(0);
    expect(document.querySelector('[data-board-showing=""]')?.textContent).toBe("");
  });
});
