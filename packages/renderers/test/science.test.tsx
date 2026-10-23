// @vitest-environment happy-dom
// The S3 simulations of the installed O level subjects (VSL-08a, VSL-30, VSL-32, VSL-46): deterministic step functions,
// readouts that match the verification tools at the declared sample points to 3 significant figures, the model's
// parameter boundaries and invariants, and controls a keyboard and a screen reader can use.
import fs from "node:fs";
import path from "node:path";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, test } from "vitest";
import { CLIENT_KEYS } from "../src/generated/keys.js";
import { electrolysisModel, equilibriumModel, equilibriumTimescale, kcAt, evaluate, GAS_CONSTANT, SIM_SETUPS, functionModel, ratesModel, ratesReadings, gasModel, parseExpression as parse, sig, transformed, type ResolvedSpec, type SimEvent, type SimModel } from "../src/index.js";
import { electrolysisPreset } from "../src/sims/electrolysis.js";
import type { Values } from "../src/sims/models.js";
import type { ElectrolysisConstants, EquilibriumSetup } from "../src/sims/science.js";
import { FIXTURES, dom, draw, fixtures, rendererOf, t } from "./helpers.js";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FIDELITY = JSON.parse(fs.readFileSync(path.join(FIXTURES, "sim_fidelity.json"), "utf8")) as Record<string, { params: Values; readouts?: Record<string, string>; samples?: Record<string, number | string>[] }[]>;
const DT = 1 / CLIENT_KEYS.sim_steps_per_s;
const SF = CLIENT_KEYS.sim_fidelity_sf;
const KINDS = Object.keys(SIM_SETUPS).sort();

function free(kind: string) {
  const f = fixtures().find((x) => x.kind === kind && (x.spec.params as { predict?: string }).predict === undefined);
  if (f === undefined) throw new Error(`no free fixture for ${kind}`);
  return f;
}

function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (Math.imul(a, 1664525) + 1013904223) >>> 0;
    return a / 4294967296;
  };
}

function randomValues(model: SimModel<unknown>, start: Values, r: () => number): Values {
  const v: Values = { ...start };
  for (const p of model.params) {
    if (p.kind === "range") {
      const steps = Math.round(((p.max ?? 1) - (p.min ?? 0)) / (p.step ?? 1));
      v[p.id] = Number(((p.min ?? 0) + Math.floor(r() * (steps + 1)) * (p.step ?? 1)).toFixed(6));
    } else if (p.kind === "choice") v[p.id] = p.choices![Math.floor(r() * p.choices!.length)]!.value;
    else v[p.id] = r() < 0.5;
  }
  return v;
}

describe("VSL-46 S3 simulations", () => {
  test("every S3 simulation has a free fixture and draws itself", () => {
    expect(KINDS.length).toBeGreaterThan(0);
    for (const kind of KINDS) {
      const root = dom(draw(free(kind).spec));
      expect(root.querySelector(`[data-kind="${kind}"]`), kind).not.toBeNull();
      expect(root.querySelector(`[data-kind="${kind}"] svg[role=img]`)?.getAttribute("aria-label"), kind).toBeTruthy();
    }
  });

  test("vsl30_sim_deterministic (S3)", () => {
    for (const kind of KINDS) {
      const { model, start } = SIM_SETUPS[kind]!(free(kind).spec);
      for (let seed = 1; seed <= 200; seed += 1) {
        const values = randomValues(model, start, seeded(seed));
        const run = () => {
          let state = Object.freeze(model.init(values));
          const trace: unknown[] = [];
          for (let i = 0; i < 30; i += 1) {
            state = Object.freeze(model.next(state, values, DT));
            trace.push(state, model.read(state, values));
          }
          return JSON.stringify(trace);
        };
        expect(run(), `${kind} seed ${seed}`).toBe(run());
      }
      for (const p of model.params) {
        expect(p.labelKey, kind).toMatch(/^sim\./);
        expect(t(p.labelKey), `${kind}: ${p.labelKey} is one or two words`).toMatch(/^\S+( \S+)?$/);
        if (p.kind === "range") expect([p.min, p.max, p.step].every((x) => typeof x === "number") && p.min! < p.max!, `${kind}: ${p.id} is bounded`).toBe(true);
      }
      for (const r of model.readouts) expect(r.sf, kind).toBeGreaterThan(0);
    }
  });

  test("vsl46_science_sim_fidelity", () => {
    let points = 0;
    // gas_laws_sim: p = nRT/V against math_evaluate; boundaries finite and positive; pV/(nT) is R everywhere.
    for (const row of FIDELITY.gas_laws_sim!) {
      const model = gasModel(Number(row.params.amount_mol), 273);
      const read = model.read(model.init(row.params), row.params);
      for (const [id, tool] of Object.entries(row.readouts!)) {
        expect(sig(read[id]!, SF), `gas ${JSON.stringify(row.params)} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
    }
    const gas = gasModel(0.01, 273);
    for (const p of gas.params) {
      for (const at of [p.min!, p.max!]) {
        const v = { temperature: 293, volume: 100, [p.id]: at };
        const r = gas.read(gas.init(v), v);
        expect(Number.isFinite(r["out.pressure"]!) && r["out.pressure"]! > 0, `gas ${p.id} at ${at}`).toBe(true);
        expect((r["out.pressure"]! * 1000 * r["out.volume"]! * 1e-6) / (0.01 * r["out.temperature"]!)).toBeCloseTo(GAS_CONSTANT, 9);
      }
    }
    // function_transform_sim: y = a f(b(x + c)) + d at sample x and the tracked point against math_evaluate.
    for (const row of FIDELITY.function_transform_sim!) {
      const p = row.params as Values & { expression: string; x: number[] };
      const f = (x: number) => evaluate(parse(p.expression), x);
      for (const sample of row.samples!) {
        expect(sig(transformed(f, p, Number(sample.x)), SF), `function ${p.expression} at ${sample.x}`).toBe(sig(Number(sample.y), SF));
        points += 1;
      }
      const slider = { min: -10, max: 10, step: 0.5, value: 0 };
      const model = functionModel(p.expression, [-6, 6], { a: slider, b: slider, c: slider, d: slider });
      const read = model.read(null, p);
      for (const [id, tool] of Object.entries(row.readouts!)) {
        expect(sig(read[id]!, SF), `function ${p.expression} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
    }
    // The tracked point follows the transformation rule: x0/b − c and a f(x0) + d; b = 0 has no point.
    const square = functionModel("x^2", [-6, 6], { a: { min: -3, max: 3, step: 1, value: 1 }, b: { min: -3, max: 3, step: 1, value: 1 }, c: { min: -5, max: 5, step: 1, value: 0 }, d: { min: -5, max: 5, step: 1, value: 0 } });
    expect(square.read(null, { a: 1, b: 0, c: 0, d: 0 })["out.point_x"]).toBeNaN();
    for (const p of square.params) for (const at of [p.min!, p.max!]) {
      const v = { a: 1, b: 1, c: 0, d: 0, [p.id]: at };
      const rows = square.table(v).rows;
      expect(rows.length).toBeGreaterThan(100);
      if (v.b !== 0) expect(rows.every(([, y]) => Number.isFinite(y)), `${p.id} at ${at}`).toBe(true);
    }
    // electrolysis_sim: each electrode's amount after Q = It against math_evaluate; charge is conserved (the moles of
    // electrons at each electrode agree) and nothing forms before the current flows.
    const k = (FIDELITY as unknown as { electrolysis_constants: ElectrolysisConstants }).electrolysis_constants;
    for (const row of FIDELITY.electrolysis_sim!) {
      const preset = electrolysisPreset(String(row.params.preset_id))!;
      const model = electrolysisModel(preset, k);
      const values = { current: Number(row.params.current), duration: Number(row.params.time), timescale: 1 };
      const read = model.read({ time: Number(row.params.time) }, values);
      for (const [id, tool] of Object.entries(row.readouts!)) {
        expect(sig(read[id]!, SF), `electrolysis ${preset.id} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
      const zero = model.read(model.init(values), values);
      expect(Object.entries(zero).filter(([id, v]) => id !== "out.time" && v !== 0), preset.id).toEqual([]);
      const electrons = (side: "cathode" | "anode") => {
        const product = preset[side];
        const amount = product.measure === "gas" ? read[`out.${side}_gas`]! / k.vm_cm3 : Math.abs(read[`out.${side}_mass`]!) / k.molar_mass[product.formula]!;
        return amount * product.electrons;
      };
      expect(electrons("cathode"), preset.id).toBeCloseTo(electrons("anode"), 12);
      expect(electrons("cathode") * k.faraday, preset.id).toBeCloseTo(read["out.charge"]!, 6);
    }
    // rates_sim: k and the product at time t against math_evaluate; a catalyst or heat only speeds it, the final amount
    // is the starting concentration either way, and the product never falls as time goes on.
    for (const row of FIDELITY.rates_sim!) {
      const p = row.params as Record<string, number>;
      const setup = { pre_exponential_s: p.a!, activation_energy_j_mol: p.ea!, catalysed_activation_energy_j_mol: p.ea! };
      const read = ratesReadings(setup, { temperature: p.temperature!, concentration: p.concentration! }, p.time!);
      for (const [id, tool] of Object.entries(row.readouts!)) {
        expect(sig(read[id]!, SF), `rates ${JSON.stringify(p)} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
    }
    const reaction = { pre_exponential_s: 8.2e6, activation_energy_j_mol: 50000, catalysed_activation_energy_j_mol: 35000 };
    const ends: number[] = [];
    for (const values of [{ temperature: 293, catalyst: false }, { temperature: 373, catalyst: false }, { temperature: 293, catalyst: true }]) {
      const v = { ...values, concentration: 0.5, timescale: 50 };
      const model = ratesModel(reaction);
      let state = model.init(v);
      let last = 0;
      for (let i = 0; i < 100_000 && !model.done(state, v); i += 1) {
        state = model.next(state, v, DT);
        const product = model.read(state, v)["out.product"]!;
        expect(product).toBeGreaterThanOrEqual(last);
        last = product;
      }
      expect(sig(last, SF), JSON.stringify(values)).toBe(sig(0.5, SF));
      ends.push(state.time);
    }
    expect(ends[1]!).toBeLessThan(ends[0]!);
    expect(ends[2]!).toBeLessThan(ends[0]!);
    // equilibrium_sim: the model run to equilibrium against math_solve's extent (and Kc against math_evaluate); matter is
    // conserved at every step (the atoms of each element stay as they were), nothing goes below zero, and a catalyst
    // reaches the same equilibrium sooner.
    const reactions = (FIDELITY as unknown as { equilibrium_reactions: Record<string, EquilibriumSetup> }).equilibrium_reactions;
    const times: Record<string, number> = {};
    for (const row of FIDELITY.equilibrium_sim!) {
      const p = row.params as { reaction: string; temperature: number; volume: number; catalyst: boolean };
      const setup = reactions[p.reaction]!;
      const model = equilibriumModel(setup, ["temperature", "volume", "catalyst"]);
      const base = { temperature: p.temperature, volume: p.volume, catalyst: false, add_reactant: 0, add_product: 0 };
      const values = { ...base, catalyst: p.catalyst, timescale: equilibriumTimescale(setup, base) };
      let state = model.init(values);
      const atoms = (c: number[]) => {
        const count: Record<string, number> = {};
        setup.species.forEach((x, i) => {
          for (const [, el, n] of x.formula.matchAll(/([A-Z][a-z]?)(\d*)/g)) count[el!] = (count[el!] ?? 0) + c[i]! * Number(n || 1);
        });
        return count;
      };
      const before = atoms(state.c);
      for (let i = 0; i < 100_000 && !model.done(state, values); i += 1) {
        state = model.next(state, values, DT);
        expect(state.c.every((c) => c >= 0)).toBe(true);
      }
      for (const [el, n] of Object.entries(atoms(state.c))) expect(n, `${p.reaction} ${el} conserved`).toBeCloseTo(before[el]!, 9);
      const read = model.read(state, values);
      for (const [id, tool] of Object.entries(row.readouts!)) {
        expect(sig(read[id]!, SF), `equilibrium ${JSON.stringify(p)} ${id}`).toBe(sig(Number(tool), SF));
        points += 1;
      }
      if (p.reaction === "hi" && p.temperature === 698) times[p.catalyst ? "with" : "without"] = state.time;
    }
    expect(times.with!).toBeLessThan(times.without!);
    expect(kcAt(reactions.hi!, 698)).toBeCloseTo(54, 12);
    expect(points).toBeGreaterThanOrEqual(64);
  });
});

async function mount(spec: ResolvedSpec, events: SimEvent[] = []) {
  const R = rendererOf(spec.type);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<R.Component spec={spec} step={0} labels="shown" focus={[]} size={{ width: 480, height: 320 }} reducedMotion onPartActivate={() => undefined} t={t} onSimEvent={(e) => events.push(e)} visible />);
  });
  return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}

describe("VSL-32 S3 simulations", () => {
  test("vsl32_sim_a11y_audit (S3)", async () => {
    const axe = (await import("axe-core")).default;
    for (const kind of KINDS) {
      const f = free(kind);
      const events: SimEvent[] = [];
      const { container, unmount } = await mount(f.spec, events);
      const controls = [...container.querySelectorAll<HTMLInputElement | HTMLSelectElement>("input, select")];
      expect(controls.length, f.id).toBeGreaterThanOrEqual(2);
      for (const c of controls) {
        const label = container.querySelector(`label[for="${c.id}"]`);
        expect((label?.textContent ?? "").trim().length, `${f.id}: ${c.id} has a visible label`).toBeGreaterThan(0);
        if (c instanceof HTMLInputElement && c.type === "range") {
          expect(c.getAttribute("aria-valuetext") ?? "", `${f.id}: ${c.id} announces its value`).toContain(c.value);
        }
      }
      // A large Reset, and the text mode one control away.
      const reset = [...container.querySelectorAll("button")].find((b) => b.textContent === t("sim.reset"));
      expect(reset, f.id).toBeDefined();
      const table = [...container.querySelectorAll("button")].find((b) => b.textContent === t("sim.show_table"))!;
      await act(async () => table.click());
      expect(container.querySelector("[data-sim-table] tbody tr"), `${f.id}: the text mode has rows`).not.toBeNull();
      const result = await axe.run(container, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
      expect(result.violations.map((v) => `${v.id}: ${v.help}`), f.id).toEqual([]);
      await unmount();
    }
  }, 60_000);

  test("a simulation that settles keeps going from where it is when a control changes", () => {
    const { model, start } = SIM_SETUPS.gas_laws_sim!(free("gas_laws_sim").spec);
    let state = model.init(start);
    for (let i = 0; i < 10; i += 1) state = model.next(state, start, DT);
    const next = { ...start, volume: 150 };
    expect(model.adjust!(state, start, next)).toBe(state);
  });
});
