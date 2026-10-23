// @vitest-environment happy-dom
// Predict, observe, explain (VSL-47): the simulation is locked until the student's own prediction is in, the
// prediction cannot change once the run starts, the result is set beside it, the explanation is drawn in the
// simulation's own picture, and every scenario is a case where its pack misconception's usual guess is wrong.
import fs from "node:fs";
import path from "node:path";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, test } from "vitest";
import { CLIENT_KEYS } from "../src/generated/keys.js";
import { circuitModel, comparePrediction, observeScenario, SCENARIOS, SIM_SETUPS, sig, titrationModel, type ResolvedSpec, type Scenario, type SimEvent } from "../src/index.js";
import type { SimModel, Values } from "../src/sims/models.js";
import { fixtures, rendererOf, ROOT, t } from "./helpers.js";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DT = 1 / CLIENT_KEYS.sim_steps_per_s;
const EN = JSON.parse(fs.readFileSync(path.join(ROOT, "packages/i18n/locales/en.json"), "utf8")) as Record<string, string>;
const SUBJECT_DIRS: Record<string, string> = { phy: "phy", chm: "chm", mth: "mth" };
const KINDS = [...new Set(SCENARIOS.map((s) => s.kind))].sort();

function predictFixture(kind: string) {
  const f = fixtures().find((x) => x.kind === kind && (x.spec.params as { predict?: string }).predict !== undefined);
  if (f === undefined) throw new Error(`no predict fixture for ${kind}`);
  return f;
}

async function mount(spec: ResolvedSpec, reducedMotion = true, events: SimEvent[] = []) {
  const R = rendererOf(spec.type);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<R.Component spec={spec} step={0} labels="shown" focus={[]} size={{ width: 480, height: 320 }} reducedMotion={reducedMotion} onPartActivate={() => undefined} t={t} onSimEvent={(e) => events.push(e)} visible />);
  });
  return { container, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}

/** Type into a React-controlled field. */
async function type(el: HTMLTextAreaElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function button(container: HTMLElement, key: string): HTMLButtonElement {
  return [...container.querySelectorAll("button")].find((b) => b.textContent === t(key))!;
}

function modelOf(s: Scenario, start: Values): SimModel<unknown> {
  if (SIM_SETUPS[s.kind] !== undefined) return SIM_SETUPS[s.kind]!(predictFixture(s.kind).spec).model;
  if (s.kind === "circuit_sim") return circuitModel(Object.keys(start).filter((k) => /^R\d$/.test(k)).sort()) as SimModel<unknown>;
  return titrationModel(CLIENT_KEYS.sim_titration_rate_cm3_s) as SimModel<unknown>;
}

/** The simulation's starting values for a scenario, as its renderer builds them from the resolved params. */
function startOf(s: Scenario): Values {
  // The S3 simulations build their starting values from the resolved spec, whose params are the scenario's start.
  if (SIM_SETUPS[s.kind] !== undefined) return SIM_SETUPS[s.kind]!(predictFixture(s.kind).spec).start;
  const p = s.start as Record<string, unknown>;
  if (s.kind === "circuit_sim") {
    const rs = p.resistors as { id: string; resistance: number }[];
    return { emf: p.emf as number, arrangement: p.arrangement as string, switch: p.switch_closed !== false, ...Object.fromEntries(rs.map((r) => [r.id, r.resistance])) };
  }
  const acid = p.acid as { concentration: number };
  const base = p.base as { concentration: number };
  return { volume: 0, tap: false, indicator: p.indicator as string, acid_concentration: acid.concentration, base_concentration: base.concentration, acid_volume: p.acid_volume as number };
}

describe("VSL-47 locking", () => {
  test("vsl47_locked_until_predicted", async () => {
    for (const kind of KINDS) {
      const f = predictFixture(kind);
      const events: SimEvent[] = [];
      const { container, unmount } = await mount(f.spec, true, events);
      // The simulation is drawn but visibly locked: no controls, no readings, no table, nothing to run.
      expect(container.querySelector("[data-sim-locked]")?.textContent, f.id).toContain(t("sim.predict.locked"));
      expect(container.querySelector("[data-sim-locked] [aria-hidden='true']"), f.id).not.toBeNull();
      expect(container.querySelectorAll("input[type=range], select, input[type=checkbox], dd").length, f.id).toBe(0);
      for (const key of ["sim.play", "sim.reset", "sim.record", "sim.show_table"]) expect(button(container, key), `${f.id}: ${key}`).toBeUndefined();
      // The question is asked, and the student's own words come first: no choices and no lock-in before writing.
      expect(container.querySelector("[data-sim-question]")?.textContent, f.id).toBeTruthy();
      expect(container.querySelector("[data-sim-choices]"), f.id).toBeNull();
      const commit = button(container, "sim.predict.commit");
      expect(commit.disabled, f.id).toBe(true);
      await type(container.querySelector("textarea")!, "   ");
      expect(button(container, "sim.predict.commit").disabled, `${f.id}: blank is not a prediction`).toBe(true);
      await type(container.querySelector("textarea")!, "My guess, in my words.");
      expect(container.querySelectorAll("[data-sim-choices] input[type=radio]").length, `${f.id}: choices follow the writing`).toBeGreaterThanOrEqual(2);
      expect(button(container, "sim.predict.commit").disabled, f.id).toBe(false);
      expect(events.filter((e) => e.type.startsWith("sim.")), `${f.id}: nothing ran`).toEqual([]);
      await unmount();
    }
  });

  test("vsl47_prediction_fixed_after_run", async () => {
    const f = predictFixture("circuit_sim");
    const events: SimEvent[] = [];
    const { container, unmount } = await mount(f.spec, true, events);
    await type(container.querySelector("textarea")!, "Less current, there are two resistors in the way.");
    await act(async () => container.querySelector<HTMLInputElement>("input[value=falls]")!.click());
    await act(async () => button(container, "sim.predict.commit").click());
    // The prediction is shown as text, not a field: there is no way left to change it, even after Reset.
    expect(container.querySelector("[data-sim-predict]")).toBeNull();
    expect(container.querySelector("[data-sim-predicted]")?.textContent).toContain("Less current, there are two resistors in the way.");
    expect(container.querySelector("[data-sim-choice=falls]")?.textContent).toBe(t("poe.circuit_parallel.choice.falls"));
    expect(container.querySelector("[data-sim-phase]")?.getAttribute("data-sim-phase")).toBe("observe");
    await act(async () => button(container, "sim.reset").click());
    expect(container.querySelector("[data-sim-predict]")).toBeNull();
    expect(container.querySelector("[data-sim-predicted]")?.textContent).toContain("Less current");
    const committed = events.filter((e) => e.type === "sim.prediction_committed");
    expect(committed).toHaveLength(1);
    expect(committed[0]).toMatchObject({ scenario_id: "poe.phy.circuit_series_to_parallel.v1", choice: "falls", correct: false, common_guess: true,
      misconception_id: "mc.phy.o.parallel_adding_branch_raises_resistance", prediction: "Less current, there are two resistors in the way." });
    // After the run the simulation is free to explore, with bounded, labelled controls; readouts stay off until ticked.
    expect(container.querySelectorAll("input[type=range]").length).toBeGreaterThan(0);
    expect(container.querySelectorAll("dd")).toHaveLength(0);
    const readings = [...container.querySelectorAll("label")].find((l) => l.textContent === t("sim.readings"))!.querySelector("input")!;
    await act(async () => readings.click());
    expect(container.querySelectorAll("dd").length).toBeGreaterThan(0);
    await unmount();
  });
});

describe("VSL-47 comparison", () => {
  test("vsl47_result_beside_prediction", async () => {
    // Circuit: series to parallel; the current rises from 0.300 A to 1.20 A (6 V across 20 Ω, then 5 Ω).
    const circuit = predictFixture("circuit_sim");
    const c = await mount(circuit.spec, false);
    await type(c.container.querySelector("textarea")!, "It goes down.");
    await act(async () => button(c.container, "sim.predict.commit").click());
    const happened = c.container.querySelector("[data-sim-happened]")!;
    expect(happened.getAttribute("data-sim-happened")).toBe("true");
    expect(happened.textContent).toContain(t("poe.circuit_parallel.outcome", { before: "0.300 A", after: "1.20 A" }));
    expect(c.container.querySelector("[data-sim-predicted]")?.textContent).toContain("It goes down.");
    // No choice was made: the comparison stands on the student's words alone, with no "usual guess" line.
    expect(c.container.querySelector("[data-sim-common-guess]")).toBeNull();
    await c.unmount();

    // Titration, animated: the result waits for the run, then reads the end point the model reached.
    const titration = predictFixture("titration_sim");
    const r = await mount(titration.spec, false);
    await type(r.container.querySelector("textarea")!, "Double, so 50 cm³.");
    await act(async () => r.container.querySelector<HTMLInputElement>("input[value=double]")!.click());
    await act(async () => button(r.container, "sim.predict.commit").click());
    expect(r.container.querySelector("[data-sim-happened]")?.getAttribute("data-sim-happened")).toBe("running");
    await r.unmount();
    const done = await mount(titration.spec, true);
    await type(done.container.querySelector("textarea")!, "Double, so 50 cm³.");
    await act(async () => done.container.querySelector<HTMLInputElement>("input[value=double]")!.click());
    await act(async () => button(done.container, "sim.predict.commit").click());
    expect(done.container.querySelector("[data-sim-happened]")?.textContent).toContain(t("poe.titration_double.outcome", { after: "12.5 cm³" }));
    expect(done.container.querySelector("[data-sim-choice=double]")?.textContent).toBe("50.0 cm³");
    expect(done.container.querySelector("[data-sim-common-guess]")?.textContent).toBe(t("sim.predict.common_guess"));
    await done.unmount();
  });

  test("vsl47_explained_in_the_sims_own_picture", async () => {
    for (const kind of KINDS) {
      const chart = SCENARIOS.find((s) => s.kind === kind)!.explain.chart;
      const f = predictFixture(kind);
      const events: SimEvent[] = [];
      const { container, unmount } = await mount(f.spec, true, events);
      await type(container.querySelector("textarea")!, "A first idea.");
      const choices = [...container.querySelectorAll<HTMLInputElement>("[data-sim-choices] input")];
      await act(async () => choices[choices.length - 1]!.click());
      await act(async () => button(container, "sim.predict.commit").click());
      // One line on how it differed, then the explanation: a chart plus one sentence, never before the line.
      expect(container.querySelector("[data-sim-explanation]"), f.id).toBeNull();
      expect(container.querySelector("label[for$='-why']")?.textContent, f.id).toBe(t("sim.predict.why"));
      const why = [...container.querySelectorAll("textarea")].find((x) => x.id.endsWith("-why"))!;
      expect(why.getAttribute("placeholder"), f.id).toBe(t("sim.predict.why_placeholder"));
      expect(button(container, "sim.predict.explain").disabled, f.id).toBe(true);
      await type(why, "It went the other way because of the paths.");
      await act(async () => button(container, "sim.predict.explain").click());
      const explanation = container.querySelector("[data-sim-explanation]")!;
      expect(explanation, f.id).not.toBeNull();
      expect(explanation.querySelector(`[data-sim-chart=${chart}] svg[role=img]`)?.getAttribute("aria-label"), f.id).toBeTruthy();
      expect(explanation.querySelectorAll("p").length, `${f.id}: the chart carries it, not a paragraph`).toBeLessThanOrEqual(2);
      if (chart === "curve") {
        expect(explanation.querySelector("[data-sim-result-mark]")?.textContent, f.id).toContain("12.5");
        expect(explanation.querySelector("[data-sim-guess-mark]")?.textContent, `${f.id}: the prediction is drawn beside the result`).toBe(t("sim.predict.your_prediction"));
      } else if (chart === "bars") {
        const s = SCENARIOS.find((x) => x.kind === kind)!;
        expect(explanation.querySelectorAll("[data-sim-chart=bars] svg").length, f.id).toBe(s.explain.chart === "bars" ? s.explain.readouts.length : 0);
        if (kind === "circuit_sim") expect(explanation.textContent, f.id).toContain("1.20 A");
      } else {
        // Before and after in one picture: both drawn, each marked where it ends.
        for (const run of ["before", "after"]) {
          expect(explanation.querySelector(`[data-sim-run=${run}]`)?.getAttribute("points"), `${f.id}: ${run}`).toBeTruthy();
          expect(explanation.querySelector(`[data-sim-end=${run}]`), `${f.id}: ${run} end`).not.toBeNull();
        }
      }
      expect(events.find((e) => e.type === "sim.explained"), f.id).toMatchObject({ explanation: "It went the other way because of the paths.", misconception_id: SCENARIOS.find((s) => s.kind === kind)!.misconception_id });
      await unmount();
    }
  });

  test("vsl47_flow_a11y_audit", async () => {
    const axe = (await import("axe-core")).default;
    const rules = { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } };
    for (const kind of KINDS) {
      const f = predictFixture(kind);
      const { container, unmount } = await mount(f.spec, true);
      expect((await axe.run(container, rules)).violations.map((v) => `${v.id}: ${v.help}`), `${f.id} predict`).toEqual([]);
      await type(container.querySelector("textarea")!, "A first idea.");
      expect((await axe.run(container, rules)).violations.map((v) => `${v.id}: ${v.help}`), `${f.id} choices`).toEqual([]);
      await act(async () => button(container, "sim.predict.commit").click());
      const why = [...container.querySelectorAll("textarea")].find((x) => x.id.endsWith("-why"))!;
      await type(why, "One line.");
      await act(async () => button(container, "sim.predict.explain").click());
      expect((await axe.run(container, rules)).violations.map((v) => `${v.id}: ${v.help}`), `${f.id} explained`).toEqual([]);
      await unmount();
    }
  }, 60_000);
});

describe("VSL-47 misconception tie-in", () => {
  test("vsl47_scenarios_tied_to_pack_misconceptions", () => {
    const kinds = new Set(SCENARIOS.map((s) => s.kind));
    expect(kinds.has("circuit_sim") && kinds.has("titration_sim"), "one physics and one chemistry scenario").toBe(true);
    for (const s of SCENARIOS) {
      // The misconception and its KCs are the pack's own.
      const file = path.join(ROOT, "content/curriculum", SUBJECT_DIRS[s.subject]!, "o/misconceptions", `${s.misconception_id}.yaml`);
      expect(fs.existsSync(file), `${s.id}: ${s.misconception_id} is in the pack`).toBe(true);
      const record = fs.readFileSync(file, "utf8");
      for (const kc of s.kc_ids) expect(record, `${s.id}: ${kc} is one of the misconception's KCs`).toContain(`- ${kc}`);
      // One usual guess and one right answer, never the same choice.
      const common = s.choices.filter((c) => c.common_guess);
      const correct = s.choices.filter((c) => c.correct);
      expect([common.length, correct.length], s.id).toEqual([1, 1]);
      expect(common[0]!.id, s.id).not.toBe(correct[0]!.id);
      // Every word is in the catalogue.
      for (const key of ["question", "outcome", "explain"]) expect(EN[`poe.${s.key}.${key}`], `${s.id} ${key}`).toBeTruthy();
      for (const c of s.choices) if (c.value === undefined || c.labelled === true) expect(EN[`poe.${s.key}.choice.${c.id}`], `${s.id} ${c.id}`).toBeTruthy();
      // The model says the usual guess is wrong and the right answer is right.
      const start = startOf(s);
      const model = modelOf(s, start);
      const seen = observeScenario(model, s, start, DT);
      const sf = model.readouts.find((r) => r.id === s.observe)!.sf;
      const before = seen.before[s.observe]!;
      const after = seen.after[s.observe]!;
      const holds = (id: string): boolean => {
        const choice = s.choices.find((c) => c.id === id)!;
        if (choice.readout !== undefined) return (seen.after[choice.readout] ?? 0) > 0;
        if (choice.value !== undefined) return sig(choice.value, sf) === sig(after, sf);
        const direction = sig(after, sf) === sig(before, sf) ? "same" : after > before ? "rises" : "falls";
        return id === direction;
      };
      expect(holds(correct[0]!.id), `${s.id}: the right answer is what the model does`).toBe(true);
      expect(holds(common[0]!.id), `${s.id}: the usual guess is wrong`).toBe(false);
      expect(comparePrediction(s, { text: "x", choice: common[0]!.id }), s.id).toEqual({ correct: false, common_guess: true });
      expect(comparePrediction(s, { text: "x", choice: null }), s.id).toEqual({ correct: null, common_guess: false });
    }
  });

  test("each kind's schema offers exactly its scenarios", () => {
    for (const kind of KINDS) {
      // A renderer-owned schema, or the specification's contract for the kinds it has one for (VSL-46).
      const own = path.join(ROOT, `packages/renderers/src/schemas/${kind}.schema.json`);
      const file = fs.existsSync(own) ? own : path.join(ROOT, `services/agent-core/agent_core/contracts/schemas/visuals/kinds/${kind}.schema.json`);
      const schema = JSON.parse(fs.readFileSync(file, "utf8")) as { properties: { predict: { enum: string[] } } };
      expect(schema.properties.predict.enum.sort(), kind).toEqual(SCENARIOS.filter((s) => s.kind === kind).map((s) => s.id).sort());
    }
  });
});
