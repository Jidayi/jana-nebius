import { readFileSync } from "node:fs";
import path from "node:path";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { SHIPPED, PSEUDO, type Locale } from "@jana/i18n";
import { convertEntry, convertMath, type PracticeItem } from "@jana/client-core";
import { defaultRegistry } from "@jana/ui";
import { registerVisuals } from "../src/visuals.js";
import { RENDERERS, sig } from "@jana/renderers";
import { GalleryView, STATES } from "@jana/ui/gallery";
import { LocaleProvider } from "../../../packages/ui/src/i18n.js";
import { Tex } from "../../../packages/ui/src/maths/Tex.js";
import { MarkdownBlock } from "../../../packages/ui/src/markdown/Markdown.js";
import { accountingAmount } from "../../../packages/renderers/src/notation.js";
import { answerOf } from "../../../packages/ui/src/learn/items.js";

afterEach(cleanup);
const golden = JSON.parse(readFileSync(path.resolve(import.meta.dirname, "../../../packages/ui/gallery/notation-golden.json"), "utf8")) as { area: string; source?: string; alternate?: string; latex?: string; operators?: string[]; mode?: "chem"; value?: number; figures?: number; shown?: string; currency?: string; brackets?: boolean; unit?: string }[];

test.each([...SHIPPED, ...PSEUDO])("loc09_notation_golden: %s", (locale: Locale) => {
  expect(new Set(golden.map((g) => g.area))).toEqual(new Set(["arithmetic", "algebra", "decimal", "fractions", "vectors", "chemistry", "significant_figures", "accounting", "constants"]));
  for (const row of golden) {
    if (row.area === "significant_figures") { expect(sig(row.value!, row.figures!)).toBe(row.shown); continue; }
    if (row.area === "accounting") { expect(accountingAmount(row.source!, row.currency, row.brackets)).toBe(row.shown); continue; }
    if (row.area === "constants") {
      const original = STATES.find((s) => s.id === "board.canonical")!;
      const state = structuredClone(original); state.context.locale = locale;
      const knowns = (state.payload.events as Record<string, unknown>[]).find((e) => e.type === "board.knowns")!;
      knowns.knowns = [{ known_id: "kn_g", symbol: "g", label: "acceleration due to gravity", value: row.source, unit: row.unit, source: "question", check_id: null }];
      const { container } = render(<GalleryView state={state} />);
      expect(container.querySelector("[data-knowns]")?.textContent).toContain(row.source);
      expect(container.querySelector("[data-knowns]")?.textContent).not.toContain("9,8"); cleanup(); continue;
    }
    const result = row.source === null || row.area === "vectors" ? null : row.mode ? convertEntry(row.source!, row.mode) : convertMath(row.source!);
    if (result) expect(result.error, row.source).toBeNull();
    const latex = result?.latex ?? row.latex!;
    if (row.latex) expect(latex).toBe(row.latex);
    if (row.alternate) expect(convertMath(row.alternate).latex).toBe(latex);
    const { container } = render(<LocaleProvider locale={locale}><Tex tex={latex} display /></LocaleProvider>);
    expect(container.querySelector("math")).not.toBeNull();
    expect(container.querySelector('annotation[encoding="application/x-tex"]')?.textContent).toBe(latex);
    for (const operator of row.operators ?? []) expect(container.querySelector("math")?.textContent).toContain(operator);
    if (row.area === "fractions") expect(container.querySelector("mfrac")).not.toBeNull();
    if (row.area === "vectors") { expect(container.querySelector("mover")).not.toBeNull(); expect(container.querySelector('[mathvariant="bold"]')).not.toBeNull(); }
    if (row.area === "chemistry") { expect(container.querySelector("msub")).not.toBeNull(); expect(container.textContent).toContain(row.source!.includes("<=>") ? "⇌" : "→"); expect(container.textContent).toContain("(g)"); }
    cleanup();
  }
  const { container } = render(<LocaleProvider locale={locale}><MarkdownBlock text="Use 1/2 of the amount in the next line." /></LocaleProvider>);
  expect(container.textContent).toContain("1/2"); expect(container.querySelector(".katex")).toBeNull();
});

test("decimal-comma normalization preserves function separators and answer precision", () => {
  for (const [source, latex] of [["frac(1,2)", "\\frac{1}{2}"], ["sqrt(1,5)", "\\sqrt{1.5}"], ["frac((1,5),2)", "\\frac{(1.5)}{2}"], [",5+1", ".5 + 1"], ["1,50", "1.50"]]) expect(convertMath(source!).latex).toBe(latex);
  expect(convertEntry("1,50 m/s", "units")).toMatchObject({ serialised: "1.50 m/s", error: null });
  const part: PracticeItem["parts"][number] = { part_id: "a", prompt: "Give the speed.", marks: 1, uses_parts: [], input: { kind: "numeric", unit_prompt: "Unit" } };
  expect(answerOf(part, { value: "1,50", unit: "m/s" })).toMatchObject({ kind: "numeric", value: "1.50", unit: "m/s" });
  expect(accountingAmount("unavailable")).toBe("unavailable");
});


test.each([...SHIPPED, ...PSEUDO])("the live accounting and simulation views use the notation rules: %s", (locale: Locale) => {
  const original = STATES.find((s) => s.component === "VisualViewer" && s.payload.type === "financial_statements" && s.state === "canonical")!;
  const source = JSON.stringify(original); const state = structuredClone(original); state.context.locale = locale;
  delete (state.payload.params as Record<string, unknown>).currency;
  const computed = state.payload.computed as { labels: Record<string, string> };
  computed.labels[Object.keys(computed.labels)[0]!] = "-12345.60";
  const registry = registerVisuals(defaultRegistry(), RENDERERS);
  const { container } = render(<GalleryView state={state} registry={registry} />);
  expect(container.textContent).toContain("($12,345.60)"); expect(JSON.stringify(original)).toBe(source); cleanup();
  const sim = structuredClone(STATES.find((s) => s.id === "visual-viewer.canonical.projectile-sim")!); sim.context.locale = locale; sim.context.reducedMotion = false;
  const view = render(<GalleryView state={sim} registry={registry} />);
  expect(view.container.querySelectorAll("dl dt .text-meta").length).toBeGreaterThan(0);
  expect([...view.container.querySelectorAll("dl dd")].map((node) => node.textContent)).toContain("20.0 m");
});
