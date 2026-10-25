// @vitest-environment happy-dom
// The S3 Biology kinds (VSL-05, VSL-46) against their engine-resolved fixtures: each renders itself from its fixture in
// the light and dark themes with stable part ids, a text alternative and a data table, and its params validate against
// the kind's specification contract. The numbers drawn (Punnett ratios, band order) are the resolution's.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { errors } from "@jana/contracts-ts/client";
import type { ResolvedSpec } from "../src/index.js";
import { ROOT, dom, draw, fixtures, focusableParts, rendererOf, resolveTheme, stepsOf, t } from "./helpers.js";

const BIOLOGY = ["diagram_comparison", "microscope_view", "cycle_diagram", "food_web", "punnett_square", "classification_key", "pedigree_chart", "gel_electrophoresis"];
const PART_ID = /^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$/;
const ALL = fixtures();
const byId = (id: string) => ALL.find((f) => f.id === id)!;

describe("VSL-05", () => {
  test("vsl05_biology_kinds_render", () => {
    for (const kind of BIOLOGY) {
      const found = ALL.filter((f) => f.kind === kind);
      expect(found.length, `${kind} has a fixture`).toBeGreaterThan(0);
      const R = rendererOf(kind);
      expect(R.schema, kind).toBe(`visuals/kinds/${kind}`);
      for (const f of found) {
        // The params validate against the kind's contract on the client too (UIA-20), and the spec is a resolved one.
        expect(R.check(f.spec.params), f.id).toEqual([]);
        expect(errors(`visuals/kinds/${kind}`, f.spec.params), f.id).toEqual([]);
        expect(errors("visuals/visual-spec#/$defs/resolved", f.spec), f.id).toEqual([]);
        const markup = draw(f.spec);
        expect(draw(f.spec), `${f.id} draws the same twice`).toBe(markup);
        for (const theme of ["light", "dark"] as const) {
          const { text, unresolved } = resolveTheme(markup, theme);
          expect(unresolved, `${f.id} ${theme}`).toEqual([]);
          expect(text, `${f.id} ${theme}`).not.toMatch(/var\(--/);
        }
        // The kind draws itself, not the words fallback, and is named by its generated alt text.
        const drawn = dom(markup).querySelector(`[data-kind="${kind}"]`);
        expect(drawn, `${f.id} draws itself`).not.toBeNull();
        expect(drawn!.getAttribute("aria-label"), f.id).toBe(f.spec.alt.summary);
        expect(f.spec.alt.summary.length, f.id).toBeGreaterThan(40);
        expect(R.alt(f.spec, -1, "en"), f.id).toBe(f.spec.alt.summary);
        // Stable part ids: the resolution's list, every one on screen at some step, in the declared order.
        const ids = R.parts(f.spec).filter((p) => p.focusable).map((p) => p.id);
        expect(ids.length, f.id).toBeGreaterThan(2);
        for (const id of ids) expect(id, f.id).toMatch(PART_ID);
        expect(new Set(ids).size, `${f.id}: ids are unique`).toBe(ids.length);
        const seen = new Set<string>();
        for (let step = -1; step < Math.max(1, stepsOf(f.spec)); step += 1) {
          const onScreen = focusableParts(dom(draw(f.spec, { step })));
          expect(onScreen, `${f.id} step ${step}`).toEqual(ids.filter((id) => onScreen.includes(id)));
          for (const id of onScreen) seen.add(id);
        }
        expect([...seen].sort(), f.id).toEqual([...ids].sort());
        // A template kind offers its values as a table (LOC-16, VSL-46), with catalogue keys for its columns.
        if (R.table !== undefined) {
          const table = R.table(f.spec);
          expect(table.rows.length, f.id).toBeGreaterThan(0);
          for (const row of table.rows) expect(row.length, f.id).toBe(table.columns.length);
          for (const column of table.columns) expect(t(column), `${f.id}: ${column}`).not.toBe(column);
        }
      }
    }
    // Each of the eight Biology catalogue entries has a gallery fixture: the six kinds of TABLE VSL-05a, a labelled
    // library diagram and a process sequence on it.
    const dir = path.join(ROOT, "packages/ui/gallery/states");
    const states = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) as { component: string; payload: { type?: string; ref?: string; params?: { sequence?: string } } });
    const viewer = states.filter((s) => s.component === "VisualViewer");
    for (const kind of BIOLOGY) expect(viewer.some((s) => s.payload.type === kind), `${kind} gallery state`).toBe(true);
    const library = viewer.filter((s) => s.payload.type === "library_diagram" && (s.payload.ref ?? "").startsWith("dgm.bio."));
    expect(library.length, "a labelled Biology diagram").toBeGreaterThan(0);
    expect(library.some((s) => s.payload.params?.sequence !== undefined), "a Biology process sequence").toBe(true);
  });

  test("Punnett cells, classes and ratios are the resolution's, traced to their checks", () => {
    const mono = byId("punnett-square").spec;
    const c = mono.computed as { grid: string[][]; genotype_classes: { genotype: string; probability: string }[]; labels: Record<string, string>; check_ids: string[] };
    expect(c.grid).toEqual([["TT", "Tt"], ["Tt", "tt"]]);
    expect(c.labels).toMatchObject({ genotype_ratio: "1 : 2 : 1", phenotype_ratio: "3 : 1" });
    expect(c.genotype_classes.map((k) => k.probability)).toEqual(["1/4", "1/2", "1/4"]);
    for (const id of c.check_ids) expect(mono.numbers_from).toContain(id);
    const root = dom(draw(mono));
    expect(root.querySelector('[data-label-for="genotype_ratio"]')?.textContent).toBe("1 TT : 2 Tt : 1 tt");
    expect(root.querySelector('[data-label-for="phenotype_ratio"]')?.textContent).toBe("3 tall : 1 short");
    // A sex-linked cross writes each allele on its X chromosome.
    const linked = dom(draw(byId("punnett-sex-linked").spec));
    expect(linked.querySelector('[data-part="parent1"] sup')?.textContent).toBe("H");
    // In hidden mode the offspring and ratios are blank, the parts still reachable.
    const hidden = dom(draw(mono, { labels: "hidden" }));
    expect(hidden.querySelector("[data-label-for]")).toBeNull();
    expect(focusableParts(hidden)).toEqual(focusableParts(root));
  });

  test("a gel's bands run largest first, smaller ones further from the wells", () => {
    const gel = byId("gel-electrophoresis").spec as ResolvedSpec;
    const c = gel.computed as { ladder: { bp: number; position: number }[]; lanes: { bands: { bp: number; position: number }[] }[] };
    for (const lane of [c.ladder, ...c.lanes.map((l) => l.bands)]) {
      expect(lane.map((b) => b.bp)).toEqual([...lane.map((b) => b.bp)].sort((a, b) => b - a));
      for (let i = 1; i < lane.length; i += 1) expect(lane[i]!.position).toBeGreaterThan(lane[i - 1]!.position);
    }
    // The same size sits at the same distance in every lane (one logarithmic scale for the gel).
    const at = new Map<number, number>();
    for (const band of [...c.ladder, ...c.lanes.flatMap((l) => l.bands)]) {
      if (at.has(band.bp)) expect(band.position).toBe(at.get(band.bp));
      at.set(band.bp, band.position);
    }
  });

  test("a comparison marks the library's declared differences, never a step highlight", () => {
    const spec = byId("diagram-comparison").spec;
    const root = dom(draw(spec, { step: -1 }));
    const marked = [...root.querySelectorAll("[data-difference]")].map((el) => el.getAttribute("data-part"));
    expect(marked).toEqual(["left.cell_wall", "left.vacuole", "left.chloroplast"]);
    expect(root.querySelector("[data-highlighted]")).toBeNull();
  });
});
