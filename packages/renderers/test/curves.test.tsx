// @vitest-environment happy-dom
// The A level graphs (VSL-07, VSL-46): exponential_curve, distribution_curve and data_plot draw what their resolution
// computed and nothing else. The marked half-life or time constant sits at the tool's point, the shaded probability is
// the tool's and covers exactly the event's outcomes, the line of best fit and its gradient triangle run between the
// tool's end points, and every table holds the plotted values.
import { describe, expect, test } from "vitest";
import type { ResolvedSpec } from "../src/index.js";
import { dataPointPart } from "../src/curves.js";
import { dom, draw, fixtures, rendererOf, t, texts } from "./helpers.js";

const ALL = fixtures();
const byId = (id: string) => ALL.find((f) => f.id === id)!.spec;
type Pt = [number, number];

function labels(spec: ResolvedSpec): Record<string, string> {
  return (spec.computed as { labels?: Record<string, string> }).labels ?? {};
}

function circle(root: HTMLElement, part: string): [number, number] {
  const c = root.querySelector(`[data-part="${part}"] circle`)!;
  return [Number(c.getAttribute("cx")), Number(c.getAttribute("cy"))];
}

describe("VSL-46 A level graphs", () => {
  test("every A level graph fixture draws itself with a table of its plotted values", () => {
    for (const kind of ["exponential_curve", "distribution_curve", "data_plot"]) {
      const specs = ALL.filter((f) => f.kind === kind);
      expect(specs.length, kind).toBeGreaterThan(0);
      for (const f of specs) {
        expect(dom(draw(f.spec)).querySelector(`[data-kind="${kind}"] svg, svg[data-kind="${kind}"]`), f.id).not.toBeNull();
        const table = rendererOf(kind).table!(f.spec);
        expect(table.rows.length, f.id).toBeGreaterThan(0);
        for (const row of table.rows) expect(row.length, f.id).toBe(table.columns.length);
        for (const column of table.columns) expect(t(column), `${f.id}: ${column}`).not.toBe(column);
      }
    }
  });

  test("an exponential curve marks the tool's half-life or time constant at the value the tool gives there", () => {
    const decay = byId("exponential-curve");
    const root = dom(draw(decay));
    const computed = decay.computed as { curve: Pt[]; mark: { t: number; value: number } };
    expect(root.querySelector('[data-part="curve"] polyline')!.getAttribute("points")!.split(" ")).toHaveLength(computed.curve.length);
    // 800 Bq falls to 400 Bq at ln 2 / 0.2 = 3.47 s (math_evaluate); the point is drawn there, on the curve.
    expect([labels(decay).half_life, labels(decay)["half_life.value"]]).toEqual(["3.47", "400"]);
    expect(computed.mark.value).toBe(400);
    // The axes run 0 to 20 s across x = 52 to 460, and 0 to 1.1 × 800 Bq up from y = 280 to 36.
    const [cx, cy] = circle(root, "half_life");
    expect(cx).toBeCloseTo(52 + (computed.mark.t / 20) * 408, 6);
    expect(cy).toBeCloseTo(280 - (400 / 880) * 244, 6);
    expect(texts(root)).toEqual(expect.arrayContaining(["3.47 s", "400 Bq", t("visual.exponential.half_life")]));
    // Charging rises towards its final value (dashed), with the time constant 1 / k marked at 1 − 1/e of it.
    const charge = byId("exponential-curve-charge");
    expect([labels(charge).time_constant, labels(charge)["time_constant.value"]]).toEqual(["2.00", "3.79"]);
    expect(dom(draw(charge)).querySelector('line[stroke-dasharray][aria-hidden="true"]')).not.toBeNull();
  });

  test("a distribution shades exactly the event's outcomes and shows the tool's probability", () => {
    // N(50, 10²): P(40 ≤ X ≤ 65) = Φ(1.5) − Φ(−1) = 0.7745 (math_integrate).
    const normal = byId("distribution-curve");
    expect(labels(normal).shade).toBe("0.7745");
    const root = dom(draw(normal));
    expect(texts(root)).toEqual(expect.arrayContaining(["P(40 ≤ X ≤ 65)", "= 0.7745"]));
    expect(root.querySelector('[data-part="shade"] [data-formula]')?.textContent).toBe("P(40 ≤ X ≤ 65)");
    // The shaded region starts and ends at the interval's ends.
    const window = (normal.computed as { window: [number, number] }).window;
    const at = (v: number) => 52 + ((v - window[0]) / (window[1] - window[0])) * (460 - 52);
    const d = root.querySelector('[data-part="shade"] path')!.getAttribute("d")!;
    const xs = [...d.matchAll(/[ML](-?[\d.]+),/g)].map((m) => Number(m[1]));
    expect(Math.min(...xs)).toBeCloseTo(at(40), 1);
    expect(Math.max(...xs)).toBeCloseTo(at(65), 1);
    // B(20, 0.3): P(X ≤ 4) = 0.2375 over the five bars 0 to 4; Po(3.5): P(X ≥ 6) over the bars from 6 up.
    const binomial = byId("distribution-curve-binomial");
    expect(labels(binomial).shade).toBe("0.2375");
    expect(dom(draw(binomial)).querySelectorAll('[data-part="shade"] rect')).toHaveLength(5);
    const poisson = byId("distribution-curve-poisson");
    const bars = (poisson.computed as { bars: Pt[] }).bars;
    expect(labels(poisson).shade).toBe("0.1424");
    expect(dom(draw(poisson)).querySelectorAll('[data-part="shade"] rect')).toHaveLength(bars.filter(([k]) => k >= 6).length);
    // The bars are the tool's: P(X = k) sums to the shaded probability over the event (to the 4 figures shown).
    const binomialBars = (binomial.computed as { bars: Pt[] }).bars;
    expect(binomialBars.filter(([k]) => k <= 4).reduce((a, [, h]) => a + h, 0)).toBeCloseTo(0.2375, 4);
    expect(rendererOf("distribution_curve").table!(binomial).rows[4]).toEqual(["4", "0.130421"]);
  });

  test("a data plot's line of best fit and gradient triangle run between the tool's points", () => {
    const spec = byId("data-plot");
    const root = dom(draw(spec));
    const line = (spec.computed as { line: Pt[] }).line;
    expect(labels(spec)).toEqual({ "fit.gradient": "1.99", "fit.intercept": "0.0524", "gradient.dx": "5.00", "gradient.dy": "9.93" });
    // One cross per data point, each its own part, in the request's order.
    const points = (spec.params as { points: { id: string }[] }).points;
    for (const p of points) expect(root.querySelector(`[data-part="${dataPointPart(p.id)}"] path`), p.id).not.toBeNull();
    const fit = root.querySelector('[data-part="fit"] line')!;
    const triangle = root.querySelector('[data-part="gradient"] path')!.getAttribute("d")!;
    const corners = [...triangle.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    expect(corners[0]).toEqual([Number(Number(fit.getAttribute("x1")).toFixed(2)), Number(Number(fit.getAttribute("y1")).toFixed(2))]);
    expect(corners[2]).toEqual([Number(Number(fit.getAttribute("x2")).toFixed(2)), Number(Number(fit.getAttribute("y2")).toFixed(2))]);
    expect(line[1]![0] - line[0]![0]).toBe(5);
    expect(texts(root)).toEqual(expect.arrayContaining(["= 1.99 cm/N", "5.00 N", "9.93 cm", "= 0.0524 cm"]));
    expect(rendererOf("data_plot").table!(spec).rows).toEqual(points.map((p) => [p.id, String((p as unknown as { x: number }).x), String((p as unknown as { y: number }).y)]));
    // Without a fit, only the points are drawn.
    const bare = { ...spec, params: { ...(spec.params as object), fit: "none" }, computed: { check_ids: [] } } as unknown as ResolvedSpec;
    const plain = dom(draw(bare));
    expect(plain.querySelector('[data-part="fit"], [data-part="gradient"], [data-part="intercept"]')).toBeNull();
    expect(plain.querySelectorAll("[data-part]")).toHaveLength(points.length);
  });

  test("a point id becomes a part id by the engine's rule, and a graph with nothing computed shows its words", () => {
    expect(dataPointPart("run-1.a")).toBe("run_1_a");
    expect(dataPointPart("p0")).toBe("p0");
    for (const id of ["exponential-curve", "distribution-curve", "distribution-curve-binomial"]) {
      const spec = { ...byId(id), computed: { check_ids: [] } } as unknown as ResolvedSpec;
      const html = draw(spec);
      expect(html, id).not.toContain("<svg");
      expect(html, id).toContain(spec.alt.summary);
    }
  });
});
