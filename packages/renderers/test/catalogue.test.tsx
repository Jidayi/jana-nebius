// @vitest-environment happy-dom
// The S2 visual catalogue against its engine-resolved fixtures (VSL-03, VSL-10, VSL-11, VSL-14, VSL-19, VSL-29, VSL-33,
// VSL-36, DSN-18, LOC-15, LOC-16) and the oracle rule that every figure a visual shows is traced (VSL-12).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { CLIENT_KEYS } from "../src/generated/keys.js";
import { CONTENT_COLOURS } from "../src/generated/content_colours.js";
import { RENDERERS, stepState, type ResolvedSpec } from "../src/index.js";
import { ROOT, catalogue, dom, draw, fixtures, focusableParts, rendererOf, resolveTheme, stepsOf, t, texts } from "./helpers.js";

const ALL = fixtures();
const byKind = (kind: string) => ALL.filter((f) => f.kind === kind);
const S2_SPEC_KINDS = catalogue().filter((k) => k.channel === "visual.spec");

describe("VSL-03", () => {
  test("vsl03_core_kinds_render", () => {
    const core = S2_SPEC_KINDS.filter((k) => k.group === "core");
    expect(core.length).toBeGreaterThanOrEqual(26);
    for (const kind of core) {
      const fixture = byKind(kind.kind)[0];
      expect(fixture, `${kind.kind} has a canonical fixture`).toBeDefined();
      const root = dom(draw(fixture!.spec));
      expect(root.querySelector(`[data-kind="${kind.kind}"]`), `${kind.kind} draws itself, not the words fallback`).not.toBeNull();
      expect(focusableParts(root).length, kind.kind).toBeGreaterThan(0);
    }
    // The gap additions and simulations render the same way.
    for (const kind of S2_SPEC_KINDS.filter((k) => k.group !== "core")) {
      const fixture = byKind(kind.kind)[0]!;
      expect(dom(draw(fixture.spec)).querySelector(`[data-kind="${kind.kind}"]`), kind.kind).not.toBeNull();
    }
  });

  test("vsl03_core_fixture_coverage", () => {
    const dir = path.join(ROOT, "packages/ui/gallery/states");
    const states = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) as { component: string; payload: { type?: string; labels?: string; ref?: string } });
    const covered = (kind: string, mode: string, ref?: (r: string) => boolean) =>
      states.some((s) => s.component === "VisualViewer" && s.payload.type === kind && s.payload.labels === mode && (ref === undefined || ref(s.payload.ref ?? "")));
    for (const kind of S2_SPEC_KINDS) {
      for (const mode of rendererOf(kind.kind).labelModes) expect(covered(kind.kind, mode), `${kind.kind} in ${mode} mode`).toBe(true);
    }
    // TABLE VSL-03a lists Physics apparatus and Chemistry lab apparatus as two entries of one kind.
    for (const subject of ["phy", "chm"]) {
      for (const mode of rendererOf("library_diagram").labelModes) {
        if (mode === "quiz" && subject === "phy") continue;
        expect(covered("library_diagram", mode, (r) => r.startsWith(`dgm.${subject}.`)), `library_diagram (${subject}) in ${mode} mode`).toBe(true);
      }
    }
    // The board entries are drawn by the board, whose states are in the gallery too.
    for (const component of ["Board", "BoardStep"]) expect(states.some((s) => s.component === component), component).toBe(true);
  });
});

describe("VSL-10", () => {
  test("vsl10_cumulative_steps", () => {
    const base = ALL.find((f) => f.id === "library-heart")!.spec;
    const spec = {
      ...base,
      steps: [{ highlight: ["vena_cava"], hide: ["aorta"] }, { highlight: ["right_atrium"], reveal: ["aorta"] }, { hide: ["pulmonary_vein"] }, { highlight: ["left_ventricle"], hide: ["right_atrium"] }],
    } as unknown as ResolvedSpec;
    const fresh = draw(spec, { step: 1 });
    // 0 -> 3 -> 1: the state at step 1 is recomputed from step 0, so going back shows exactly steps 0 and 1.
    draw(spec, { step: 0 });
    draw(spec, { step: 3 });
    expect(draw(spec, { step: 1 })).toBe(fresh);
    const state = stepState(spec, 1);
    expect([...state.highlight]).toEqual(["right_atrium"]);
    expect([...state.hidden]).toEqual([]);
    const at3 = stepState(spec, 3);
    expect([...at3.hidden].sort()).toEqual(["pulmonary_vein", "right_atrium"]);
    const root = dom(fresh);
    expect(root.querySelector('[data-part="aorta"]')).not.toBeNull();
    expect(root.querySelector('[data-part="right_atrium"]')?.getAttribute("data-highlighted")).toBe("true");
    expect(root.querySelector('[data-part="vena_cava"]')?.getAttribute("data-highlighted")).toBeNull();
  });
});

describe("VSL-11", () => {
  test("vsl11_hidden_labels_absent", () => {
    for (const f of ALL.filter((x) => x.modes.includes("hidden"))) {
      const shown = dom(draw(f.spec, { labels: "shown" }));
      const hidden = dom(draw(f.spec, { labels: "hidden" }));
      const labelTexts = [...shown.querySelectorAll("[data-label-for]")].map((el) => (el.textContent ?? "").trim()).filter((s) => s.length > 1);
      const drawn = texts(hidden);
      const names = [...hidden.querySelectorAll("[aria-label]")].map((el) => el.getAttribute("aria-label") ?? "").join(" | ");
      for (const label of labelTexts) {
        expect(drawn.some((x) => x === label || (label.length > 3 && x.includes(label))), `${f.id}: label "${label}" is still drawn`).toBe(false);
        expect(names.includes(label), `${f.id}: label "${label}" is in an accessible name`).toBe(false);
      }
      expect(hidden.querySelector("[data-label-for]"), f.id).toBeNull();
      expect(focusableParts(hidden), `${f.id}: parts stay focusable`).toEqual(focusableParts(shown));
    }
  });
});

describe("VSL-14 and LOC-15", () => {
  test("vsl14_alt_all_kinds", () => {
    for (const f of ALL) {
      const alt = f.spec.alt;
      expect(alt.summary.length, f.id).toBeGreaterThan(20);
      expect(alt.summary, f.id).not.toMatch(/undefined|null|NaN|\{|\}/);
      expect(alt.steps.length, f.id).toBe(Math.min(20, stepsOf(f.spec)));
      const R = rendererOf(f.kind);
      expect(R.alt(f.spec, -1, "en")).toBe(alt.summary);
      // A screen reader reads the summary as the visual's name in shown mode.
      const named = dom(draw(f.spec)).querySelector(`[data-kind="${f.kind}"]`);
      expect(named?.getAttribute("aria-label"), f.id).toBe(alt.summary);
    }
  });

  test("loc15_diagram_parts_named", () => {
    // Simulations are named by their labelled controls and readouts (VSL-32, audited in sims.test.tsx).
    for (const f of ALL.filter((x) => !x.kind.endsWith("_sim"))) {
      const parts = rendererOf(f.kind).parts(f.spec).filter((p) => p.focusable);
      const root = dom(draw(f.spec));
      parts.forEach((p, i) => {
        const el = root.querySelector(`[data-part="${CSS.escape(p.id)}"]`);
        if (el === null) return; // a part shown at another step; the union over steps is checked in VSL-19
        const name = el.getAttribute("aria-label") ?? el.closest("label")?.textContent ?? "";
        if (el.matches("input, select")) return; // native controls take their name from their visible label
        expect(name.startsWith(p.name), `${f.id}: ${p.id} is named ${name}`).toBe(true);
        expect(name, f.id).toContain(t("visual.part.position", { index: i + 1, count: parts.length }));
      });
      expect(f.spec.alt.summary.trim().length, f.id).toBeGreaterThan(0);
    }
  });

  test("loc15_hidden_mode_names", async () => {
    const axe = (await import("axe-core")).default;
    for (const f of ALL.filter((x) => x.modes.includes("hidden"))) {
      for (const mode of f.modes.filter((m) => m !== "shown")) {
        const shown = dom(draw(f.spec));
        const labels = [...shown.querySelectorAll("[data-label-for]")].map((el) => (el.textContent ?? "").trim()).filter((s) => s.length > 1);
        const container = document.createElement("div");
        container.innerHTML = draw(f.spec, { labels: mode });
        document.body.appendChild(container);
        for (const el of container.querySelectorAll<HTMLElement>("[data-part][tabindex]")) {
          const name = el.getAttribute("aria-label") ?? "";
          expect(name.length, `${f.id} ${mode}: ${el.getAttribute("data-part")} has a name`).toBeGreaterThan(0);
          for (const label of labels) expect(name.includes(label), `${f.id} ${mode}: "${label}" in "${name}"`).toBe(false);
        }
        const result = await axe.run(container, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
        expect(result.violations.map((v) => `${v.id}: ${v.help}`), `${f.id} ${mode}`).toEqual([]);
        container.remove();
      }
    }
  }, 120_000);
});

describe("VSL-19", () => {
  test("vsl19_parts_match_dom", () => {
    for (const f of ALL) {
      const R = rendererOf(f.kind);
      const ids = R.parts(f.spec).filter((p) => p.focusable).map((p) => p.id);
      expect(ids, `${f.id}: parts() is the resolved spec's list`).toEqual(f.spec.parts.filter((p) => p.focusable).map((p) => p.id));
      const seen: string[] = [];
      for (let step = -1; step < Math.max(1, stepsOf(f.spec)); step += 1) {
        const onScreen = focusableParts(dom(draw(f.spec, { step })));
        // Every focusable element is a declared part, in the declared order.
        expect(onScreen.filter((id) => !ids.includes(id)), `${f.id} step ${step}`).toEqual([]);
        expect(onScreen, `${f.id} step ${step} keeps the parts' order`).toEqual(ids.filter((id) => onScreen.includes(id)));
        for (const id of onScreen) if (!seen.includes(id)) seen.push(id);
      }
      // A predict scenario's simulation is locked until the student predicts (VSL-47): its controls and readouts, and
      // so its parts, appear only after the prediction is locked in (predict.test.tsx checks them there).
      if ((f.spec.params as { predict?: string }).predict !== undefined) expect(seen, `${f.id}: no part before the prediction`).toEqual([]);
      else expect(seen.sort(), `${f.id}: every part appears`).toEqual([...ids].sort());
    }
  });
});

describe("VSL-12", () => {
  test("every figure a visual shows is traced to a check, a known or pack data", () => {
    let figures = 0;
    // A simulation's live readouts come from its client model, which is cross-checked against the tools instead
    // (vsl31_sim_matches_tools); its starting readouts are traced here through the other fixtures' rule.
    for (const f of ALL.filter((x) => !x.kind.endsWith("_sim"))) {
      const root = dom(draw(f.spec));
      root.querySelectorAll("[data-presentation], [data-formula], [data-blank-for], thead, caption, select, input, button").forEach((el) => el.remove());
      const shown = texts(root).join("   ").replace(/[A-Za-z]\d+/g, " ").replace(/\b\d{3}°/g, (m) => String(Number(m.slice(0, 3))) + "°");
      for (const n of shown.match(/-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\/\d+)?/g) ?? []) {
        figures += 1;
        const ok = f.claims.some((c) => fraction(c) === fraction(n) || c === n || c === n.replace(/^-/, ""));
        expect(ok, `${f.id}: ${n} is not traced (claims ${f.claims.join(", ")})`).toBe(true);
      }
    }
    expect(figures).toBeGreaterThan(100);
  });
});

function fraction(text: string): number {
  const [a, b] = text.replace(/,/g, "").split("/");
  return b === undefined ? Number(a) : Number(a) / Number(b);
}

describe("VSL-29", () => {
  test("vsl29_presets_render", () => {
    const presetDirs = fs.readdirSync(path.join(ROOT, "content/curriculum")).flatMap((subject) => {
      const dir = path.join(ROOT, "content/curriculum", subject, "o", "presets");
      return fs.existsSync(dir) ? fs.readdirSync(dir).map((f) => f.replace(/\.yaml$/, "")) : [];
    });
    expect(presetDirs.length).toBeGreaterThanOrEqual(8);
    for (const id of presetDirs) {
      const f = ALL.find((x) => (x.spec as { ref?: string }).ref === id);
      expect(f, `${id} has a resolved fixture`).toBeDefined();
      expect(rendererOf(f!.kind).check(f!.spec.params), id).toEqual([]);
      expect(dom(draw(f!.spec)).querySelector(`[data-kind="${f!.kind}"]`), id).not.toBeNull();
    }
  });
});

describe("DSN-18", () => {
  test("dsn18_svg_uses_tokens", () => {
    const library = ALL.filter((f) => f.kind === "library_diagram");
    expect(library.length).toBeGreaterThanOrEqual(5);
    for (const f of library) {
      const svg = (f.spec.computed as { svg: string }).svg;
      expect(svg, f.id).not.toMatch(/(fill|stroke|stop-color)="(#|rgb|hsl)/i);
      for (const m of svg.matchAll(/(?:fill|stroke|stop-color)="([^"]+)"/g)) expect(m[1], f.id).toMatch(/^(none|transparent|currentColor|var\(--(color|content)-[a-z0-9-]+\)|url\(#[\w.-]+\))$/);
      for (const theme of ["light", "dark"] as const) {
        const { text, unresolved } = resolveTheme(draw(f.spec), theme);
        expect(unresolved, `${f.id} ${theme}`).toEqual([]);
        expect(text, `${f.id} ${theme}`).not.toMatch(/var\(--/);
      }
    }
    // The vetted renderers draw with tokens too.
    for (const f of ALL) expect(resolveTheme(draw(f.spec), "dark").unresolved, f.id).toEqual([]);
  });

  test("dsn18_content_colour_named", () => {
    const uses: string[] = [];
    const markups = [...ALL.map((f) => draw(f.spec)), draw(ALL.find((f) => f.id === "titration-sim")!.spec)];
    for (const markup of markups) {
      const root = dom(markup);
      for (const el of root.querySelectorAll("[data-content-colour]")) {
        const colour = el.getAttribute("data-content-colour") ?? "";
        uses.push(colour);
        expect(Object.keys(CONTENT_COLOURS), colour).toContain(colour);
        expect(el.getAttribute("stroke"), `${colour} has its line-strong outline`).toBe("var(--color-line-strong)");
        const name = t(CONTENT_COLOURS[colour as keyof typeof CONTENT_COLOURS].nameKey);
        expect((el.closest("svg")?.textContent ?? "").toLowerCase(), `${colour} is named in text`).toContain(name.toLowerCase());
      }
    }
    expect(uses.length).toBeGreaterThanOrEqual(2);
  });
});

describe("LOC-16", () => {
  test("loc16_table_alternative", () => {
    const graphs = catalogue().filter((k) => k.renderer === "graph" && k.stage <= "S2");
    expect(graphs.map((g) => g.kind).sort()).toEqual(["break_even_chart", "function_graph", "motion_graph", "statistics_chart", "titration_curve"]);
    for (const kind of graphs) {
      const R = rendererOf(kind.kind);
      expect(R.table, `${kind.kind} offers Show as table`).toBeDefined();
      for (const f of byKind(kind.kind)) {
        const table = R.table!(f.spec);
        expect(table.rows.length, f.id).toBeGreaterThan(0);
        for (const row of table.rows) expect(row.length, f.id).toBe(table.columns.length);
        for (const column of table.columns) expect(t(column), `${f.id}: ${column} is a catalogue key`).not.toBe(column);
      }
    }
    // The same values: the titration table is the tool's curve point for point; the chart table is the question's data.
    const titration = byKind("titration_curve")[0]!;
    const points = (titration.spec.computed as { points: [number, number][] }).points;
    expect(rendererOf("titration_curve").table!(titration.spec).rows.map((r) => r.map(Number))).toEqual(points);
    const bars = byKind("statistics_chart").find((f) => f.id === "statistics-chart")!;
    expect(rendererOf("statistics_chart").table!(bars.spec).rows).toEqual([["Mon", "12"], ["Tue", "9"], ["Wed", "15"]]);
  });
});

describe("VSL-33", () => {
  test("vsl33_render_budgets", () => {
    const p95 = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length * 0.95)]!;
    for (const f of ALL) {
      const R = rendererOf(f.kind);
      for (let i = 0; i < 3; i += 1) draw(f.spec);
      const times: number[] = [];
      for (let i = 0; i < 20; i += 1) {
        const start = performance.now();
        draw(f.spec);
        times.push(performance.now() - start);
      }
      expect(p95(times), `${f.id} first render`).toBeLessThanOrEqual(CLIENT_KEYS.visual_first_render_ms);
      if (stepsOf(f.spec) > 1) {
        const start = performance.now();
        draw(f.spec, { step: 1 });
        expect(performance.now() - start, `${f.id} step change`).toBeLessThanOrEqual(CLIENT_KEYS.visual_step_paint_ms);
      }
      expect(f.spec.parts.length, f.id).toBeLessThanOrEqual(R.budget.maxParts);
      if (f.kind === "library_diagram") {
        expect(new TextEncoder().encode((f.spec.computed as { svg: string }).svg).length, f.id).toBeLessThanOrEqual(CLIENT_KEYS.visual_library_svg_max_kb * 1024);
        expect(f.spec.parts.length).toBeLessThanOrEqual(CLIENT_KEYS.visual_library_max_parts);
      }
      if (f.kind === "function_graph") {
        const curves = Object.values((f.spec.computed as { curves: Record<string, [number, number][][]> }).curves);
        expect(curves.length).toBeLessThanOrEqual(CLIENT_KEYS.visual_curve_max_count);
        for (const segments of curves) expect(segments.flat().length).toBeLessThanOrEqual(CLIENT_KEYS.visual_curve_max_points);
      }
    }
  });
});

describe("VSL-36", () => {
  test("vsl36_offline_content_only", () => {
    // Networking off and no model: every network path throws, and rendering never reaches one.
    const attempts: string[] = [];
    const saved = { fetch: globalThis.fetch, XMLHttpRequest: globalThis.XMLHttpRequest, WebSocket: globalThis.WebSocket };
    globalThis.fetch = (async (input: unknown) => {
      attempts.push(String(input));
      throw new Error("offline");
    }) as typeof fetch;
    (globalThis as { XMLHttpRequest: unknown }).XMLHttpRequest = function refuse() { attempts.push("xhr"); throw new Error("offline"); };
    (globalThis as { WebSocket: unknown }).WebSocket = function refuse() { attempts.push("ws"); throw new Error("offline"); };
    try {
      // Every library drawing and preset of the S2 packs, from its pre-resolved spec (and the lesson visuals, which
      // the packs do not carry yet), renders.
      const packVisuals: string[] = [];
      for (const subject of fs.readdirSync(path.join(ROOT, "content/curriculum"))) {
        for (const kind of ["diagrams", "presets"]) {
          const dir = path.join(ROOT, "content/curriculum", subject, "o", kind);
          if (fs.existsSync(dir)) packVisuals.push(...fs.readdirSync(dir).filter((f) => f.endsWith(".yaml")).map((f) => f.replace(/\.yaml$/, "")));
        }
      }
      expect(packVisuals.length).toBeGreaterThanOrEqual(12);
      for (const id of packVisuals) {
        const f = ALL.find((x) => (x.spec as { ref?: string }).ref === id);
        expect(f, id).toBeDefined();
        const markup = draw(f!.spec);
        expect(dom(markup).querySelector(`[data-kind="${f!.kind}"]`), id).not.toBeNull();
        expect(markup, `${id} refers to nothing outside the app`).not.toMatch(/(href|src)="(https?:)?\/\//);
      }
      for (const f of ALL) draw(f.spec);
      expect(attempts).toEqual([]);
    } finally {
      globalThis.fetch = saved.fetch;
      globalThis.XMLHttpRequest = saved.XMLHttpRequest;
      globalThis.WebSocket = saved.WebSocket;
    }
    // The renderer sources name no remote resource: fonts, KaTeX and drawings are bundled.
    const src = path.join(ROOT, "packages/renderers/src");
    const walk = (dir: string): string[] => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]));
    for (const file of walk(src)) expect(fs.readFileSync(file, "utf8"), file).not.toMatch(/https?:\/\/(?!jana\.dev\/|json-schema\.org\/draft\/)/);
  });
});

describe("register parity", () => {
  test("every S2 visual.spec kind has exactly one renderer", () => {
    const kinds = RENDERERS.map((r) => r.kind);
    expect(new Set(kinds).size).toBe(kinds.length);
    expect(S2_SPEC_KINDS.map((k) => k.kind).filter((k) => !kinds.includes(k))).toEqual([]);
  });
});
