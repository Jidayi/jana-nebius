// @vitest-environment happy-dom
// The online sketch's vetted renderer (VSL-43, VSL-44, DSN-10a): it draws exactly the resolved elements, in the
// rough-sketch style (the sketch tokens' dashed stroke, labels in the hand font), and its accessible name is the
// engine's alt text. Nothing outside the closed vocabulary is ever drawn.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { SKETCH_DASH, SKETCH_STROKE, SketchView, type ResolvedSketch } from "../src/index.js";

const SKETCH: ResolvedSketch = {
  sketch_id: `skt_${"1".repeat(26)}`, sketch_version: 1, frame: { visual_id: null, x_min: -10, x_max: 10, y_min: -10, y_max: 10 },
  elements: [
    { kind: "arrow", from: [0, 0], to: [0, -5] }, { kind: "line", from: [-8, -2], to: [8, 2] },
    { kind: "arc", center: [0, 0], radius: 2, start_deg: 0, end_deg: 30 }, { kind: "circle", center: [3, 3], radius: 1 },
    { kind: "polygon", points: [[0, 0], [2, 0], [0, 2]] }, { kind: "point", at: [1, 1], name: "A" },
    { kind: "label", at: [1, -5], text: "weight" }, { kind: "axis", axis: "x", from: -10, to: 10, ticks: [0, 5], title: "x" },
  ],
  dropped: [{ element: 8, reason: "out_of_bounds" }], checks: [], status: "not_checked", alt: "Rough sketch: 1 arrow, 1 line",
};

describe("VSL-44", () => {
  test("test_vsl44_sketch_renderer_draws_resolved_elements_rough", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<SketchView sketch={SKETCH} />);
    const drawn = [...host.querySelectorAll("[data-sketch-element]")].map((e) => e.getAttribute("data-sketch-element"));
    expect(drawn).toEqual(SKETCH.elements.map((e) => e.kind));
    // Rough strokes: the sketch tokens' width and dash on every drawn stroke but the axis.
    for (const kind of ["arrow", "line", "arc", "circle", "polygon"]) {
      const el = host.querySelector(`[data-sketch-element="${kind}"]`) as Element;
      expect(el.getAttribute("stroke-dasharray"), kind).toBe(SKETCH_DASH);
      expect(el.getAttribute("stroke-width"), kind).toBe(String(SKETCH_STROKE));
    }
    expect(host.querySelector('[data-sketch-element="label"]')?.getAttribute("class")).toContain("font-hand");
    expect(host.querySelector("svg")?.getAttribute("aria-label")).toBe(SKETCH.alt);
    // Only the closed vocabulary: no markup or foreign content inside the drawing.
    expect(host.querySelectorAll("foreignObject, script, image, use").length).toBe(0);
  });
});
