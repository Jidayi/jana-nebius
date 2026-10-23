// DSN-23 (mastery state styling) on the generated tokens and on the screens that show mastery: the subject map and the
// Progress heat map; UXS-27's grade line in the exam board's own letters only (D27); UXS-26's mock band by the same rule;
// Home's plan card words (UXS-12).
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";
import { BASE } from "@jana/i18n";
import { EMPTY_PLAN, KC_STATES, gradeShown, mockBandShown, type KcState, type ProgressView } from "@jana/client-core";
import { GalleryView, STATES } from "../gallery/index.js";
import { TOKENS } from "../src/generated/tokens.js";
import { LocaleProvider } from "../src/i18n.js";
import { ProgressContent } from "../src/progress/Progress.js";

afterEach(() => cleanup());

function luminance(colour: string): number {
  const hex = colour.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}

const ratio = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
};

type Colour = { light: string; dark: string };
const COLOURS = TOKENS.color as unknown as Record<string, Colour>;
const MASTERY = TOKENS.mastery as unknown as { states: Record<KcState, { fill: string; ink: string; pattern: string; icon: string; labelKey: string }>; rampOrder: KcState[]; minRampStep: number };

describe("DSN-23", () => {
  test("dsn23_mastery_ramp", () => {
    expect(Object.keys(MASTERY.states).sort()).toEqual([...KC_STATES].sort());
    for (const theme of ["light", "dark"] as const) {
      // Every state's label ink is readable on its own fill (4.5:1).
      for (const [state, entry] of Object.entries(MASTERY.states)) {
        expect(ratio(COLOURS[entry.ink]![theme], COLOURS[entry.fill]![theme]), `${state} ${theme}`).toBeGreaterThanOrEqual(4.5);
      }
      // The ramp darkens in light and brightens in dark, each step at least the minimum apart, so greyscale keeps order.
      const ramp = MASTERY.rampOrder.map((state) => COLOURS[MASTERY.states[state].fill]![theme]);
      expect(MASTERY.minRampStep).toBeGreaterThanOrEqual(1.5);
      for (let i = 1; i < ramp.length; i += 1) {
        const [before, after] = [luminance(ramp[i - 1]!), luminance(ramp[i]!)];
        if (theme === "light") expect(after, `${MASTERY.rampOrder[i]} ${theme}`).toBeLessThan(before);
        else expect(after, `${MASTERY.rampOrder[i]} ${theme}`).toBeGreaterThan(before);
        expect(ratio(ramp[i - 1]!, ramp[i]!), `${MASTERY.rampOrder[i - 1]} to ${MASTERY.rampOrder[i]} ${theme}`).toBeGreaterThanOrEqual(MASTERY.minRampStep);
      }
    }
    // The two states off the ramp are told apart from each other by hatch and cross-hatch, not colour.
    expect(MASTERY.states.needs_review.pattern).toBe("hatch-diagonal");
    expect(MASTERY.states.moved_on.pattern).toBe("cross-hatch");
  });

  test("dsn23_states_greyscale", () => {
    // In the subject map and the Progress heat map, every element showing a state carries its pattern class, its icon and
    // its word; once colour is gone, each state still has its own (pattern, icon, word), so no state rests on colour.
    const signature = new Map<KcState, Set<string>>();
    for (const id of ["subject-map.canonical", "progress.canonical"]) {
      const state = STATES.find((s) => s.id === id)!;
      const { container } = render(<GalleryView state={state} />);
      const marked = [...container.querySelectorAll<HTMLElement>("[data-mastery]")].filter((el) => el.getAttribute("aria-hidden") !== "true");
      expect(marked.length, id).toBeGreaterThan(0);
      for (const el of marked) {
        const kc = el.getAttribute("data-mastery") as KcState;
        const filled = el.matches("[class*='mastery-pattern-']") ? el : el.querySelector<HTMLElement>("[class*='mastery-pattern-']");
        const pattern = /mastery-pattern-([a-z-]+)/.exec(filled?.className ?? "")?.[1];
        const icon = /lucide-([a-z0-9-]+)/.exec(el.querySelector("svg")?.getAttribute("class") ?? "")?.[1];
        const word = BASE[MASTERY.states[kc].labelKey]!;
        expect(pattern, `${id} ${kc} pattern`).toBe(MASTERY.states[kc].pattern);
        expect(icon, `${id} ${kc} icon`).toBeTruthy();
        expect(`${el.getAttribute("aria-label") ?? ""} ${el.textContent ?? ""}`, `${id} ${kc} word`).toContain(word);
        const seen = signature.get(kc) ?? new Set<string>();
        seen.add(`${pattern}|${icon}|${word}`);
        signature.set(kc, seen);
      }
      cleanup();
    }
    // The heat map shows all six states; each state looks the same wherever it appears, and no two states look alike.
    expect([...signature.keys()].sort()).toEqual([...KC_STATES].sort());
    const looks = [...signature.values()].map((s) => [...s]);
    for (const look of looks) expect(look).toHaveLength(1);
    expect(new Set(looks.flat()).size).toBe(KC_STATES.length);
    // A compact cell shows its word on focus (it is narrower than 48 px).
    render(<GalleryView state={STATES.find((s) => s.id === "progress.canonical")!} />);
    const cell = document.querySelector<HTMLElement>("li[data-heat-kc]")!;
    expect(cell.tabIndex).toBe(0);
    expect(cell.querySelector("[data-cell-word]")?.className).toContain("group-focus-visible:block");
  });
});

const progress = (grade: Record<string, unknown>): ProgressView => {
  const view = STATES.find((s) => s.id === "progress.canonical")!.payload.progress as ProgressView;
  return { ...view, subjects: view.subjects.map((s) => ({ ...s, grade: grade as ProgressView["subjects"][number]["grade"] })) };
};

describe("UXS-27", () => {
  test("test_uxs27_band_in_board_letters_only", () => {
    // A subject whose pack sets no exam board letters (`no_scale`, as every pack today): nothing about a grade shows.
    expect(gradeShown({ status: "no_scale", checked: 40, needed: 30 })).toEqual({ kind: "none" });
    for (const [grade, words] of [
      [{ status: "no_scale", checked: 40, needed: 30 }, null],
      [{ status: "hidden", checked: 12, needed: 30 }, "Your grade estimate appears after 30 checked answers. 12 so far."],
      [{ status: "uncertain", checked: 40, needed: 30 }, "Not enough evidence yet for a band"],
      [{ status: "shown", checked: 40, needed: 30, band: "B", range: ["C", "A"], confidence: 0.8 }, "Likely band: B (could be C to A)"],
    ] as const) {
      render(
        <LocaleProvider locale="en">
          <ProgressContent state={{ status: "ready", progress: progress(grade) }} names={{ subject: () => "Physics", kc: () => null }} actions={{ onRetry: () => undefined }} />
        </LocaleProvider>,
      );
      expect(document.querySelector("[data-grade]")?.textContent ?? null).toBe(words);
      if (words === null) expect(document.body.textContent).not.toMatch(/band|grade estimate/i);
      cleanup();
    }
  });

  test("test_uxs26_mock_band_in_board_letters_only", () => {
    const band = { band: "C", range: ["D", "B"], score_interval: [0.4, 0.6], confidence: 0.8, message_key: "assessment.likely_band" };
    expect(mockBandShown({ grade_band: { ...band, board_neutral: false } })).toEqual({ kind: "band", band: "C", low: "D", high: "B" });
    expect(mockBandShown({ grade_band: { ...band, board_neutral: true } })).toEqual({ kind: "none" });
    expect(mockBandShown({ grade_band: null })).toEqual({ kind: "evidence" });
    expect(mockBandShown({})).toEqual({ kind: "none" });
    // Null: not enough evidence yet, said (the gallery's reviewed report).
    const reviewed = STATES.find((s) => s.id === "mock-sitting.canonical.reviewed")!;
    let { container } = render(<GalleryView state={reviewed} />);
    expect(container.querySelector("[data-grade-band]")?.textContent).toBe("Not enough evidence yet for a band");
    cleanup();
    // Absent: the paper's pack sets no board letters, so the report says nothing about a band at all (D27).
    const absent = structuredClone(reviewed);
    const result = (absent.payload as { view: { result: Record<string, unknown> } }).view.result;
    expect("grade_band" in result).toBe(true);
    delete result.grade_band;
    ({ container } = render(<GalleryView state={absent} />));
    expect(container.querySelector("[data-grade-band]")).toBeNull();
    expect(container.textContent).not.toMatch(/band/i);
  });
});

describe("UXS-12", () => {
  test("test_uxs12_plan_card_words", () => {
    // The plan card's states: estimates never read as a timer or a goal; nothing counts down or blames (LRN-35).
    const ids = STATES.filter((s) => s.component === "HomePlan").map((s) => s.id);
    expect(ids.length).toBeGreaterThanOrEqual(8);
    for (const id of ids) {
      const { container } = render(<GalleryView state={STATES.find((s) => s.id === id)!} />);
      expect(container.textContent, id).not.toMatch(/left|hurry|missed|lost|goal|limit|\bPIN\b/i);
      cleanup();
    }
    expect(EMPTY_PLAN.status).toBe("idle");
    render(<GalleryView state={STATES.find((s) => s.id === "home-plan.canonical")!} />);
    const card = screen.getByRole("region", { name: /^Next up/ });
    expect(within(card).getAllByRole("listitem")[0]!.getAttribute("data-next")).toBe("");
  });
});
