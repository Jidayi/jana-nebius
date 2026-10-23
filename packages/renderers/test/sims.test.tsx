// @vitest-environment happy-dom
// The S2 simulations (VSL-30, VSL-31, VSL-32): deterministic step functions, readouts that match the verification
// tools at the declared sample points, and controls a keyboard and a screen reader can use.
import fs from "node:fs";
import path from "node:path";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, test } from "vitest";
import { CLIENT_KEYS } from "../src/generated/keys.js";
import { SIM_SETUPS, circuitModel, projectileModel, runToEnd, sig, titrationModel, type ResolvedSpec, type SimEvent } from "../src/index.js";
import type { SimModel, Values } from "../src/sims/models.js";
import { FIXTURES, fixtures, rendererOf, t } from "./helpers.js";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FIDELITY = JSON.parse(fs.readFileSync(path.join(FIXTURES, "sim_fidelity.json"), "utf8")) as {
  g: number;
  projectile_sim: { params: Values; readouts: Record<string, string> }[];
  circuit_sim: { params: Values; readouts: Record<string, string> }[];
  titration_sim: { params: Values; samples: { volume: number; "out.ph": string }[]; end_point: string }[];
};
const DT = 1 / CLIENT_KEYS.sim_steps_per_s;
const SF = CLIENT_KEYS.sim_fidelity_sf;

function models(): SimModel<unknown>[] {
  return [projectileModel(FIDELITY.g), circuitModel(["R1", "R2", "R3"]), titrationModel(CLIENT_KEYS.sim_titration_rate_cm3_s)] as SimModel<unknown>[];
}

function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (Math.imul(a, 1664525) + 1013904223) >>> 0;
    return a / 4294967296;
  };
}

function randomValues(model: SimModel<unknown>, r: () => number): Values {
  const v: Values = { acid_concentration: 0.1, base_concentration: 0.1, acid_volume: 25 };
  for (const p of model.params) {
    if (p.kind === "range") {
      const steps = Math.round(((p.max ?? 1) - (p.min ?? 0)) / (p.step ?? 1));
      v[p.id] = Number(((p.min ?? 0) + Math.floor(r() * (steps + 1)) * (p.step ?? 1)).toFixed(6));
    } else if (p.kind === "choice") v[p.id] = p.choices![Math.floor(r() * p.choices!.length)]!.value;
    else v[p.id] = r() < 0.5;
  }
  if (v.mode === "horizontal" && v.height === 0) v.height = 1;
  return v;
}

describe("VSL-30", () => {
  test("vsl30_sim_deterministic", () => {
    for (const model of models()) {
      for (let seed = 1; seed <= 1000; seed += 1) {
        const values = randomValues(model, seeded(seed));
        const run = () => {
          let state = Object.freeze(model.init(values));
          const trace: unknown[] = [];
          for (let i = 0; i < 30; i += 1) {
            state = Object.freeze(model.next(state, values, DT));
            trace.push(state, model.read(state, values));
          }
          return JSON.stringify(trace);
        };
        expect(run(), `${model.kind} seed ${seed}`).toBe(run());
      }
      // The contract's declared parts: parameters with ranges and defaults, readouts with units and precision.
      for (const p of model.params) {
        expect(p.labelKey).toMatch(/^sim\./);
        if (p.kind === "range") expect([p.min, p.max, p.step].every((x) => typeof x === "number")).toBe(true);
      }
      for (const r of model.readouts) expect(r.sf).toBeGreaterThan(0);
    }
  });
});

describe("VSL-31", () => {
  test("vsl31_sim_matches_tools", () => {
    let points = 0;
    const projectile = projectileModel(FIDELITY.g);
    for (const row of FIDELITY.projectile_sim) {
      const read = projectile.read(runToEnd(projectile, row.params, DT), row.params);
      for (const [id, tool] of Object.entries(row.readouts)) {
        expect(sig(read[id]!, SF), `projectile ${JSON.stringify(row.params)} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
    }
    for (const row of FIDELITY.circuit_sim) {
      const ids = Object.keys(row.params).filter((k) => /^R\d$/.test(k)).sort();
      const model = circuitModel(ids);
      const read = model.read(model.init(row.params), { ...row.params, switch: true });
      for (const [id, tool] of Object.entries(row.readouts)) {
        expect(sig(read[id]!, SF), `circuit ${JSON.stringify(row.params)} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
    }
    const titration = titrationModel(CLIENT_KEYS.sim_titration_rate_cm3_s);
    for (const row of FIDELITY.titration_sim) {
      for (const sample of row.samples) {
        const read = titration.read({ volume: sample.volume }, row.params);
        expect(sig(read["out.ph"]!, SF), `titration ${JSON.stringify(row.params)} at ${sample.volume}`).toBe(sig(Number(sample["out.ph"]), SF));
        points += 1;
      }
      expect(sig(titration.read({ volume: 0 }, row.params)["out.end_point"]!, SF)).toBe(sig(Number(row.end_point), SF));
    }
    expect(points).toBeGreaterThanOrEqual(30);
  });
});

async function mount(spec: ResolvedSpec, reducedMotion: boolean, events: SimEvent[] = []) {
  const R = rendererOf(spec.type);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<R.Component spec={spec} step={0} labels="shown" focus={[]} size={{ width: 480, height: 320 }} reducedMotion={reducedMotion} onPartActivate={() => undefined} t={t} onSimEvent={(e) => events.push(e)} visible />);
  });
  return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}

describe("VSL-32", () => {
  test("vsl32_sim_a11y_audit", async () => {
    const axe = (await import("axe-core")).default;
    // The free simulations; a predict scenario's flow has its own audit in predict.test.tsx (VSL-47).
    // The free S2 simulations; the S3 ones have their own audit in science.test.tsx.
    const sims = fixtures().filter((f) => f.kind.endsWith("_sim") && SIM_SETUPS[f.kind] === undefined && (f.spec.params as { predict?: string }).predict === undefined);
    expect(sims.map((f) => f.kind).sort()).toEqual(["circuit_sim", "projectile_sim", "titration_sim"]);
    for (const f of sims) {
      const events: SimEvent[] = [];
      const { container, unmount } = await mount(f.spec, true, events);
      // Every control is a native, labelled control; ranges say their unit and their value.
      const controls = [...container.querySelectorAll<HTMLInputElement | HTMLSelectElement>("input, select")];
      expect(controls.length, f.id).toBeGreaterThanOrEqual(2);
      for (const c of controls) {
        const label = container.querySelector(`label[for="${c.id}"]`);
        expect((label?.textContent ?? "").trim().length, `${f.id}: ${c.id} has a visible label`).toBeGreaterThan(0);
        if (c instanceof HTMLInputElement && c.type === "range") {
          expect(c.getAttribute("step"), `${f.id}: ${c.id} steps`).not.toBeNull();
          expect(c.getAttribute("aria-valuetext") ?? "", `${f.id}: ${c.id} announces its value`).toContain(c.value);
          const unit = (label?.textContent ?? "").match(/\(([^)]+)\)/)?.[1];
          if (unit !== undefined) expect(c.getAttribute("aria-valuetext") ?? "", `${f.id}: ${c.id} unit`).toContain(unit);
          if (c.disabled) continue;
          // Page keys move ten steps.
          const before = Number(c.value);
          const step = Number(c.getAttribute("step"));
          await act(async () => {
            c.dispatchEvent(new KeyboardEvent("keydown", { key: "PageUp", bubbles: true }));
          });
          const after = Number((container.querySelector<HTMLInputElement>(`#${CSS.escape(c.id)}`)!).value);
          expect(after, `${f.id}: ${c.id} PageUp`).toBeCloseTo(Math.min(Number(c.getAttribute("max")), before + 10 * step), 6);
        }
      }
      expect(events.some((e) => e.type === "sim.param_changed"), f.id).toBe(true);
      // Readouts go to a polite live region, and the text mode is one control away.
      const live = container.querySelector("[aria-live='polite']");
      expect(live, f.id).not.toBeNull();
      const toggle = [...container.querySelectorAll("button")].find((b) => b.textContent === t("sim.show_table"))!;
      expect(toggle, f.id).toBeDefined();
      await act(async () => toggle.click());
      expect(container.querySelector("[data-sim-table]"), f.id).not.toBeNull();
      const reset = [...container.querySelectorAll("button")].find((b) => b.textContent === t("sim.reset"))!;
      await act(async () => reset.click());
      expect(events.some((e) => e.type === "sim.reset"), f.id).toBe(true);
      const record = [...container.querySelectorAll("button")].find((b) => b.textContent === t("sim.record"))!;
      await act(async () => record.click());
      expect(events.find((e) => e.type === "sim.reading_recorded")?.reading, f.id).toBeDefined();
      const result = await axe.run(container, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
      expect(result.violations.map((v) => `${v.id}: ${v.help}`), f.id).toEqual([]);
      await unmount();
    }
  }, 120_000);

  test("reduced motion shows each change's final state, and readouts are announced at most once a second", async () => {
    const projectile = fixtures().find((f) => f.id === "projectile-sim")!;
    const { container, unmount } = await mount(projectile.spec, true);
    const range = (projectile.spec.computed as { labels: Record<string, string> }).labels["out.range"]!;
    const readouts = [...container.querySelectorAll("dd")].map((d) => d.textContent ?? "");
    expect(readouts.some((r) => r.startsWith(range)), "the ball has landed: the distance across is the range").toBe(true);
    const speed = container.querySelector<HTMLInputElement>("input[type=range]")!;
    const live = container.querySelector("[aria-live='polite']")!;
    await act(async () => speed.dispatchEvent(new KeyboardEvent("keydown", { key: "PageUp", bubbles: true })));
    const first = live.textContent;
    await act(async () => speed.dispatchEvent(new KeyboardEvent("keydown", { key: "PageDown", bubbles: true })));
    expect(live.textContent, "a second change within the interval is not announced again").toBe(first);
    await unmount();
  });
});
