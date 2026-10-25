// @vitest-environment happy-dom
// VSL-41 (D103): a visual built in steps shows its first declared layer, then one more per step, in the renderer's
// order; its last state equals `show`; a part of a layer still to come is neither drawn nor focusable.
import { describe, expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { RENDERERS, stepCount, stepState, type ResolvedSpec } from "../src/index.js";
import { dom, draw, fixtures, focusableParts } from "./helpers.js";

function graphBuild(): ResolvedSpec {
  const spec = fixtures().find((f) => f.kind === "function_graph")!.spec;
  const parts = spec.parts.map((p) => p.id);
  const points = parts.filter((id) => spec.parts.find((p) => p.id === id)?.role === "point" && !id.includes("."));
  const answer = parts.filter((id) => id.includes("."));
  const curve = parts.filter((id) => !points.includes(id) && !answer.includes(id));
  const layers = [{ layer: "axes", part_ids: [] }, { layer: "grid", part_ids: [] }, { layer: "points", part_ids: points }, { layer: "curve", part_ids: curve }, { layer: "answer", part_ids: answer }]
    .filter((l, i) => i < 2 || l.part_ids.length > 0);
  return { ...spec, presentation: "build", layers, steps: [] };
}

describe("VSL-41", () => {
  test("test_vsl41_build_state_adds_one_layer_per_step", () => {
    const spec = graphBuild();
    const layers = spec.layers!;
    expect(stepCount(spec)).toBe(layers.length - 1);
    for (let step = -1; step < layers.length - 1; step += 1) {
      const state = stepState(spec, step);
      const later = layers.slice(step + 2).flatMap((l) => l.part_ids);
      expect([...state.unbuilt].sort()).toEqual([...later].sort());
      const root = dom(draw(spec, { step }));
      // A part still to come is not drawn: absent, or an empty placeholder marked unbuilt.
      for (const id of later) {
        const el = root.querySelector(`[data-part="${id}"]`);
        expect(el === null || (el.getAttribute("data-unbuilt") === "true" && el.childElementCount === 0)).toBe(true);
      }
      expect(focusableParts(root).some((id) => later.includes(id))).toBe(false);
    }
    // The last state equals `show`: the same markup as the visual drawn whole.
    const whole: ResolvedSpec = { ...spec, presentation: "show" };
    expect(draw(spec, { step: layers.length - 2 })).toBe(draw(whole, { step: layers.length - 2 }));
  });

  test("test_vsl41_show_and_unlayered_draw_whole", () => {
    const spec = graphBuild();
    expect(stepState({ ...spec, presentation: "show" }, -1).unbuilt.size).toBe(0);
    expect(stepState({ ...spec, layers: [] }, -1).unbuilt.size).toBe(0);
  });

  test("test_uxs57_visual_parts_dimmed", () => {
    // A spotlight on a visual (UXS-57) dims every part outside the target; the target keeps its ring.
    const spec = fixtures().find((f) => f.kind === "number_line")!.spec;
    const target = spec.parts.find((p) => p.focusable)!.id;
    const R = RENDERERS.find((r) => r.kind === "number_line")!;
    const markup = renderToStaticMarkup(<R.Component spec={spec} step={0} labels="shown" focus={[target]} spotlight size={{ width: 480, height: 200 }}
      reducedMotion onPartActivate={() => undefined} />);
    const parts = [...dom(markup).querySelectorAll("[data-part]")];
    expect(parts.find((p) => p.getAttribute("data-part") === target)?.getAttribute("data-dimmed")).toBeNull();
    expect(parts.filter((p) => p.getAttribute("data-part") !== target).every((p) => p.getAttribute("data-dimmed") === "true")).toBe(true);
    const plain = renderToStaticMarkup(<R.Component spec={spec} step={0} labels="shown" focus={[target]} size={{ width: 480, height: 200 }} reducedMotion onPartActivate={() => undefined} />);
    expect(plain).not.toContain("data-dimmed");
  });
});
