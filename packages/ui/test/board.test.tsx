// UIA-10 (cards never fold, failures promoted), UIA-18 and UXS-15 (board rows and keyboard), UIA-16 and UXS-21
// (reading anchor under layout changes), SEC-11 (model markdown inert).
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, test } from "vitest";
import { translator } from "@jana/i18n";
import { Board } from "../src/board/Board.js";
import { LocaleProvider, TranslateProvider } from "../src/i18n.js";
import { MarkdownBlock } from "../src/markdown/Markdown.js";
import { useStickyScroll } from "../src/transcript/Transcript.js";
import { TurnView } from "../src/transcript/Turn.js";
import { TutorLookProvider } from "../src/tutor/look.js";
import { Fixture, SESSION, id } from "./harness.js";

afterEach(() => cleanup());

const BOARD = `brd_${"7".repeat(26)}`;

function step(f: Fixture, i: number, status: string, owner = "student", latex = `x_${i} = ${i}`) {
  f.emit({ type: "board.step", board_id: BOARD, step_id: `stp_${String(i).padStart(26, "0")}`, index: i, latex, reason: null, owner, status, check_id: status === "correct" ? `chk_STEP${i}` : null, error: null }, null);
}

describe("UIA-10", () => {
  test("uia10_cards_never_folded", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.tool("math_solve");
    const partId = id("prt");
    f.emit({ type: "part.start", part_id: partId, kind: "card", index: 1 });
    f.emit({ type: "card.open", request_id: id("req"), part_id: partId, call_id: null, card: { card_type: "question", prompt: "Which equation would you use?", options: [{ id: "opt_0", label: "v^2 = u^2 + 2as" }], allow_free_text: false, multi: false } });
    f.emit({ type: "part.end", part_id: partId, status: "complete", duration_ms: 1 });
    f.end();
    f.render(<TurnView turnId={turnId} />);
    const card = screen.getByText("Which equation would you use?");
    expect(card.closest('[data-open="false"]')).toBeNull(); // the folded summary never hides the card
    const option = screen.getByRole("button", { name: "v^2 = u^2 + 2as" });
    option.focus();
    expect(document.activeElement).toBe(option);
  });

  test("uia10_failure_promoted", () => {
    const f = new Fixture();
    const turnId = f.startTurn();
    f.tool("math_solve");
    f.tool("math_check_step", "error");
    f.end();
    f.render(<TurnView turnId={turnId} />);
    const failure = screen.getByText("Couldn't check the working");
    expect(failure.closest('[data-open="false"]')).toBeNull();
  });
});

describe("UIA-18 and UXS-15", () => {
  test("uia18_step_status_isolated", () => {
    const f = new Fixture();
    for (let i = 0; i < 6; i += 1) step(f, i, "draft");
    const base = translator("en");
    const rows: Record<number, number> = {};
    const counting = (key: string, args?: Record<string, string | number | Date>) => {
      if (key === "board.step.number") rows[Number(args?.index)] = (rows[Number(args?.index)] ?? 0) + 1;
      return base(key, args);
    };
    f.render(<TranslateProvider t={counting}><Board sessionId={SESSION} /></TranslateProvider>);
    const before = { ...rows };
    step(f, 3, "correct"); // step 4 (index 3) is marked correct
    for (let n = 1; n <= 6; n += 1) expect(rows[n], `row ${n}`).toBe((before[n] ?? 0) + (n === 4 ? 1 : 0));
  });

  test("uia18_keyboard_board", () => {
    const f = new Fixture();
    step(f, 0, "correct", "tutor", "v^2 = u^2 + 2as");
    step(f, 1, "draft");
    step(f, 2, "awaiting");
    f.emit({ type: "board.await", board_id: BOARD, step_id: `stp_${"2".padStart(26, "0")}`, prompt: "Your turn", input_kind: "latex" }, null);
    f.render(<Board sessionId={SESSION} />);
    const rows = [...document.querySelectorAll<HTMLElement>("li[data-step-id]")];
    rows[0]!.focus();
    fireEvent.keyDown(rows[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[1]);
    fireEvent.keyDown(rows[1]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[2]);
    fireEvent.keyDown(rows[2]!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(rows[1]);
    // The check chip of a checked line is reachable and describes the check.
    expect(rows[0]!.querySelector("[data-check-id]")?.getAttribute("aria-description")).toBe("Checked by the working checker");
    expect(rows[2]!.getAttribute("aria-label")).toContain("Your turn");
  });

  test("test_d108_board_owner_mark_names_the_tutor: a tutor line shows the profile's tutor name, a student line You (UXS-15, D105, D108)", () => {
    const f = new Fixture();
    step(f, 0, "correct", "tutor", "v^2 = u^2 + 2as");
    step(f, 1, "draft", "student", "s = 10 m");
    f.render(<TutorLookProvider avatar="avatar.kite" name="Nova"><Board sessionId={SESSION} /></TutorLookProvider>);
    const rows = [...document.querySelectorAll<HTMLElement>("li[data-step-id]")];
    expect(rows[0]!.querySelector("[data-tutor-name]")?.textContent).toBe("Nova");
    expect(rows[0]!.getAttribute("aria-label")).toContain(", Nova,");
    expect(rows[0]!.textContent).not.toContain("Tutor");
    expect(rows[1]!.querySelector("[data-tutor-name]")).toBeNull();
    expect(rows[1]!.getAttribute("aria-label")).toContain(", You,");
    cleanup();
    const plain = new Fixture();
    step(plain, 0, "correct", "tutor", "v^2 = u^2 + 2as");
    plain.render(<Board sessionId={SESSION} />);
    expect(document.querySelector("li[data-step-id] [data-tutor-name]")?.textContent).toBe("Jana"); // the default (D47)
  });

  test("uxs15_keyboard_lines", () => {
    const f = new Fixture();
    step(f, 0, "correct", "student", "s = 10 m");
    f.render(<Board sessionId={SESSION} />);
    const row = document.querySelector<HTMLElement>("li[data-step-id]")!;
    // The row announces its number, owner, maths and status.
    expect(row.getAttribute("aria-label")).toBe("Step 1, You, s = 10 m, Checked");
  });

  test("test_uxs16_look_here_words_for_each_error_category", () => {
    const f = new Fixture();
    const row = (i: number, error: Record<string, unknown> | null, reason: string | null) => f.emit({ type: "board.step", board_id: BOARD, step_id: `stp_${String(i).padStart(26, "0")}`, index: i, latex: `x = ${i}`, reason, owner: "student", status: "incorrect", check_id: null, error }, null);
    row(0, { category: "sign", message_key: "board.error.sign" }, null);
    row(1, null, "units"); // a core that names the category as the line's reason
    row(2, { category: "copy", message_key: "board.error.not_in_this_build" }, null); // an unknown key reads by its category
    row(3, null, "the student's own reason");
    f.render(<Board sessionId={SESSION} />);
    const notes = [...document.querySelectorAll("li[data-step-id]")].map((li) => li.querySelector("[data-look-here]")?.textContent ?? null);
    expect(notes).toEqual(["Look at the sign of each term.", "Look at the units: they don't match across this line.", "Check this number against the question.", null]);
    // The raw category is never shown as words; a real reason is.
    expect(document.body.textContent).not.toMatch(/\bunits\b(?!:)/);
    expect(document.body.textContent?.toLowerCase()).not.toContain("wrong");
    expect(document.body.textContent).toContain("the student's own reason");
  });

  test("test_uxs15_student_line_typeset", () => {
    const f = new Fixture();
    step(f, 0, "correct", "student", "v^2 = u^2 + 2as");
    step(f, 1, "correct", "student", "14^2");
    step(f, 2, "correct", "student", "a = 9.8 m/s^2, s = 20 m");
    step(f, 3, "awaiting", "student", "v_1 = 3");
    step(f, 4, "unchecked", "student", "I think it is about 20");
    f.render(<Board sessionId={SESSION} />);
    const rows = [...document.querySelectorAll<HTMLElement>("li[data-step-id]")];
    // Maths input is typeset the way the tutor's lines are: no caret or underscore is left on the page as text.
    for (const row of rows.slice(0, 4)) {
      const shown = row.querySelector(".katex-html");
      expect(shown, row.getAttribute("aria-label") ?? "").not.toBeNull();
      expect(shown!.textContent).not.toMatch(/[\^_]/);
    }
    expect(rows[0]!.querySelector(".katex-html")!.textContent).toContain("2");
    // A unit is upright beside its number, a power on the unit is a superscript.
    const units = rows[2]!.querySelector(".katex-html")!;
    expect(units.querySelectorAll(".mathrm, .mord.mathrm").length).toBeGreaterThan(0);
    expect(units.querySelector(".msupsub")).not.toBeNull();
    // A line of words stays as the student wrote it.
    expect(rows[4]!.querySelector(".katex")).toBeNull();
    expect(rows[4]!.textContent).toContain("I think it is about 20");
    // The row still announces what was typed.
    expect(rows[0]!.getAttribute("aria-label")).toBe("Step 1, You, v^2 = u^2 + 2as, Checked");
  });
});

/** A scroll container whose children report the layout we give them (happy-dom has no layout engine). */
function Anchored({ above }: { above: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { onScroll } = useStickyScroll(ref, above);
  return (
    <div ref={ref} onScroll={onScroll} data-testid="scroller">
      <div data-anchor data-testid="above" style={{ height: above }} />
      <div data-anchor data-testid="reading" />
    </div>
  );
}

describe("UIA-16 and UXS-21", () => {
  test("uxs21_reading_anchor", () => {
    let above = 100;
    const { getByTestId, rerender } = render(<Anchored above={above} />);
    const scroller = getByTestId("scroller");
    const reading = getByTestId("reading");
    let scrollTop = 0;
    Object.defineProperty(scroller, "scrollTop", { get: () => scrollTop, set: (v: number) => (scrollTop = v), configurable: true });
    Object.defineProperty(scroller, "scrollHeight", { get: () => 2000 + above, configurable: true });
    Object.defineProperty(scroller, "clientHeight", { get: () => 400, configurable: true });
    scroller.getBoundingClientRect = () => ({ top: 0, bottom: 400, left: 0, right: 600, width: 600, height: 400, x: 0, y: 0, toJSON: () => ({}) });
    getByTestId("above").getBoundingClientRect = () => ({ top: -scrollTop, bottom: above - scrollTop, left: 0, right: 600, width: 600, height: above, x: 0, y: -scrollTop, toJSON: () => ({}) });
    reading.getBoundingClientRect = () => ({ top: above - scrollTop + 30, bottom: above - scrollTop + 60, left: 0, right: 600, width: 600, height: 30, x: 0, y: above - scrollTop + 30, toJSON: () => ({}) });
    // The student scrolls up to read; the reading line is 30 px below the top of the view.
    scrollTop = above;
    fireEvent.scroll(scroller);
    const before = reading.getBoundingClientRect().top;
    // A disclosure above opens: 180 px of content appear above the line being read.
    above = 280;
    act(() => rerender(<Anchored above={above} />));
    expect(Math.abs(reading.getBoundingClientRect().top - before)).toBeLessThanOrEqual(1);
  });

  test("uia16_anchor_restored", () => {
    function Growing() {
      const [extra, setExtra] = useState(0);
      return (
        <>
          <button type="button" onClick={() => setExtra((e) => e + 200)}>grow</button>
          <Anchored above={100 + extra} />
        </>
      );
    }
    const { getByTestId, getByRole } = render(<Growing />);
    const scroller = getByTestId("scroller");
    let scrollTop = 0;
    let above = 100;
    Object.defineProperty(scroller, "scrollTop", { get: () => scrollTop, set: (v: number) => (scrollTop = v), configurable: true });
    Object.defineProperty(scroller, "scrollHeight", { get: () => 3000, configurable: true });
    Object.defineProperty(scroller, "clientHeight", { get: () => 400, configurable: true });
    scroller.getBoundingClientRect = () => ({ top: 0, bottom: 400, left: 0, right: 600, width: 600, height: 400, x: 0, y: 0, toJSON: () => ({}) });
    const reading = getByTestId("reading");
    getByTestId("above").getBoundingClientRect = () => ({ top: -scrollTop, bottom: above - scrollTop, left: 0, right: 600, width: 600, height: above, x: 0, y: 0, toJSON: () => ({}) });
    reading.getBoundingClientRect = () => ({ top: above - scrollTop, bottom: above - scrollTop + 30, left: 0, right: 600, width: 600, height: 30, x: 0, y: 0, toJSON: () => ({}) });
    scrollTop = 50;
    fireEvent.scroll(scroller); // detached: more than the threshold from the bottom
    const before = reading.getBoundingClientRect().top;
    above = 300;
    fireEvent.click(getByRole("button", { name: "grow" }));
    expect(Math.abs(reading.getBoundingClientRect().top - before)).toBeLessThanOrEqual(1);
  });
});

describe("SEC-11", () => {
  test("sec11_xss_payloads_inert", () => {
    const payloads = ["<script>alert(1)</script>", "[click](javascript:alert(1))", '<a href="javascript:alert(1)">x</a>', "<img src=x onerror=alert(1)>", "<svg><script>alert(1)</script></svg>", "<iframe src=x></iframe>"];
    for (const text of payloads) {
      const { container } = render(<LocaleProvider locale="en"><MarkdownBlock text={text} /></LocaleProvider>);
      expect(container.querySelector("script, img, iframe, svg, a, [href]"), text).toBeNull();
      for (const el of container.querySelectorAll("*")) for (const attr of el.attributes) expect(attr.name.startsWith("on"), text).toBe(false);
      cleanup();
    }
  });
});

test.each(["light", "dark"])("uxs16_feedback_not_colour_alone: %s", (theme) => {
  document.documentElement.dataset.theme = theme;
  for (const [status, word] of [["correct", "Checked"], ["incorrect", "Not quite"], ["equivalent_unsimplified", "Right, can be simplified"]]) {
    const f = new Fixture();
    step(f, 0, status!);
    f.render(<Board sessionId={SESSION} />);
    const row = document.querySelector<HTMLElement>("li[data-step-id]")!;
    const label = screen.getByText(word!, { exact: true });
    expect(label.querySelector("svg")).not.toBeNull();
    expect(row.getAttribute("aria-label")).toContain(word!);
    expect(row.textContent?.toLowerCase()).not.toContain("wrong");
    cleanup();
  }
  delete document.documentElement.dataset.theme;
});


test("board toolbar and scrubber navigate through one shared selection action", () => {
  const f = new Fixture(); for (let index = 0; index < 3; index++) step(f, index, "correct");
  f.render(<Board sessionId={SESSION} />);
  const range = screen.getByRole("slider", { name: "Board steps" }) as HTMLInputElement;
  expect(range.value).toBe("3");
  expect((screen.getByRole("button", { name: "Next step" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Previous step" }));
  expect(range.value).toBe("2");
  expect(f.holder.getState().boards[BOARD]?.current).toBe(`stp_${String(1).padStart(26, "0")}`);
  fireEvent.change(range, { target: { value: "1" } });
  expect((screen.getByRole("button", { name: "Previous step" }) as HTMLButtonElement).disabled).toBe(true);
  expect(f.holder.getState().boards[BOARD]?.current).toBe(`stp_${String(0).padStart(26, "0")}`);
  fireEvent.click(screen.getByRole("button", { name: "Next step" })); expect(range.value).toBe("2");
  expect(screen.getByText("Step 2 of 3")).toBeDefined();
});
