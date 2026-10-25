// @vitest-environment happy-dom
// The organic and A level chemistry kinds on the client (VSL-06, VSL-07, VSL-46): each engine-resolved fixture passes
// the kind's contract, draws itself with every declared layer's parts, and offers a complete data table; an
// illustrative equilibrium response says so; and organic_structure draws E and Z but-2-ene as two distinct, labelled
// structures from chem_organic's results (its resolution is tested in the engine against the tool's contract).
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { PENDING_RENDERERS, type ResolvedSpec } from "../src/index.js";
import { dom, draw, fixtures, focusableParts, rendererOf, t, texts } from "./helpers.js";

const KINDS = ["reaction_mechanism", "energy_levels", "orbital_boxes", "maxwell_boltzmann", "born_haber_cycle", "concentration_time", "spectrum_chart"];
const ALL = fixtures().filter((f) => KINDS.includes(f.kind));

/** A skeletal but-2-ene as chem_organic draws it: four carbons (a1-a4) and three bonds (b1-b3), the middle one double. */
function molecule(end: number): string {
  const pts: [number, number][] = [[30, 110], [70, 60], [130, 60], [170, end]];
  const bonds = [[0, 1, "b1"], [1, 2, "b2"], [2, 3, "b3"]] as const;
  const lines = bonds.map(([a, b, id]) => `<line data-part="${id}" x1="${pts[a]![0]}" y1="${pts[a]![1]}" x2="${pts[b]![0]}" y2="${pts[b]![1]}" stroke="var(--color-diagram-stroke)" stroke-width="1.5"/>`);
  const atoms = pts.map(([x, y], n) => `<circle data-part="a${n + 1}" cx="${x}" cy="${y}" r="3" fill="var(--color-diagram-stroke)"/>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 160">${lines.join("")}<line x1="70" y1="68" x2="130" y2="68" stroke="var(--color-diagram-stroke)" stroke-width="1.5"/>${atoms.join("")}</svg>`;
}

const ATOMS = ["a1", "a2", "a3", "a4"];
const BONDS = ["b1", "b2", "b3"];
const BUT_2_ENE = {
  spec_version: 1, type: "organic_structure", labels: "shown", visual_id: `vis_${"1".repeat(26)}`, status: "ok", repairs: [], steps: [],
  params: { task: "compare", representation: "skeletal", highlight_groups: ["alkene"], inputs: [{ kind: "name", value: "(E)-but-2-ene" }, { kind: "name", value: "(Z)-but-2-ene" }] },
  numbers_from: ["chk_organic_1"],
  computed: {
    structures: [
      { canonical_smiles: "C/C=C/C", formula: "C4H8", functional_groups: ["alkene"], highlighted: ["alkene"], svg: molecule(10), atom_ids: ATOMS, bond_ids: BONDS },
      { canonical_smiles: "C/C=C\\C", formula: "C4H8", functional_groups: ["alkene"], highlighted: ["alkene"], svg: molecule(110), atom_ids: ATOMS, bond_ids: BONDS },
    ],
    relationship: "stereoisomers",
    check_ids: ["chk_organic_1"],
    labels: { mol_1: "(E)-but-2-ene", "mol_1.formula": "C4H8", mol_2: "(Z)-but-2-ene", "mol_2.formula": "C4H8" },
  },
  parts: [
    { id: "mol_1", name: "(E)-but-2-ene", role: "structure", focusable: true },
    { id: "mol_1.fg_alkene", name: "alkene group", role: "region", focusable: true },
    { id: "mol_2", name: "(Z)-but-2-ene", role: "structure", focusable: true },
    { id: "mol_2.fg_alkene", name: "alkene group", role: "region", focusable: true },
    ...[1, 2].flatMap((n) => [...ATOMS, ...BONDS].map((id) => ({ id: `mol_${n}.${id}`, name: id, role: id.startsWith("a") ? "atom" : "bond", focusable: false }))),
  ],
  alt: { summary: "The skeletal formula of (E)-but-2-ene (C4H8) and (Z)-but-2-ene (C4H8); they are stereoisomers.", steps: [], locale: "en" },
} as unknown as ResolvedSpec;

describe("VSL-06", () => {
  test("vsl06_but2ene_isomers", () => {
    const organic = PENDING_RENDERERS.find((r) => r.kind === "organic_structure")!;
    expect(organic.check(BUT_2_ENE.params)).toEqual([]);
    const markup = renderToStaticMarkup(<organic.Component spec={BUT_2_ENE} step={-1} labels="shown" focus={[]} size={{ width: 480, height: 320 }} reducedMotion onPartActivate={() => undefined} t={t} />);
    const root = dom(markup);
    expect(root.querySelector('[data-kind="organic_structure"]')?.getAttribute("aria-label")).toBe(BUT_2_ENE.alt.summary);
    // Two structures side by side, each with its own name, the same formula and the same atoms and bonds.
    expect(focusableParts(root)).toEqual(["mol_1", "mol_1.fg_alkene", "mol_2", "mol_2.fg_alkene"]);
    const shown = texts(root);
    expect(shown).toContain("(E)-but-2-ene");
    expect(shown).toContain("(Z)-but-2-ene");
    expect(shown.filter((x) => x === "C4H8")).toHaveLength(2);
    expect(shown).toContain(t("visual.organic.stereoisomers"));
    for (const n of [1, 2]) {
      const atoms = [...root.querySelectorAll(`[data-part^="mol_${n}.a"]`)];
      expect(atoms).toHaveLength(4);
      // Atoms and bonds are addressable but not tab stops.
      expect(atoms.every((a) => !a.hasAttribute("tabindex"))).toBe(true);
    }
    // The drawings differ where E and Z differ: the fourth carbon is across the double bond in E, on the same side in Z.
    const end = (n: number) => root.querySelector(`[data-part="mol_${n}.a4"]`)?.getAttribute("cy");
    expect([end(1), end(2)]).toEqual(["10", "110"]);
    expect(organic.table!(BUT_2_ENE).rows).toEqual([["(E)-but-2-ene", "C4H8", "alkene"], ["(Z)-but-2-ene", "C4H8", "alkene"]]);
  });
});

describe("VSL-46", () => {
  test("vsl46_science_kind_contracts", () => {
    expect(new Set(ALL.map((f) => f.kind))).toEqual(new Set(KINDS));
    for (const f of ALL) {
      const R = rendererOf(f.kind);
      expect(R.check(f.spec.params), f.id).toEqual([]);
      const root = dom(draw(f.spec));
      expect(root.querySelector(`[data-kind="${f.kind}"]`), f.id).not.toBeNull();
      // Every part a declared build layer adds is drawn (VSL-41).
      const layers = ((f.spec as { layers?: { layer: string; part_ids: string[] }[] }).layers ?? []);
      const drawn = new Set([-1, ...Array.from({ length: f.spec.steps.length }, (_, i) => i)].flatMap((step) => focusableParts(dom(draw(f.spec, { step })))));
      for (const layer of layers) for (const id of layer.part_ids) expect(drawn.has(id), `${f.id}: ${layer.layer} adds ${id}`).toBe(true);
      // A complete table (LOC-16): rows of the declared width, columns that are catalogue keys.
      const table = R.table!(f.spec);
      expect(table.rows.length, f.id).toBeGreaterThan(0);
      for (const row of table.rows) {
        expect(row.length, f.id).toBe(table.columns.length);
        expect(row.every((cell) => cell !== "" && !/undefined|NaN/.test(cell)), `${f.id}: ${row.join(" | ")}`).toBe(true);
      }
      for (const column of table.columns) expect(t(column), `${f.id}: ${column}`).not.toBe(column);
    }
    // An illustrative equilibrium response says so and shows no time scale; a first-order graph has its axes.
    const qualitative = dom(draw(ALL.find((f) => f.id === "concentration-time-equilibrium")!.spec));
    expect(qualitative.querySelector("[data-illustrative]")?.textContent).toBe(t("visual.conc.illustrative"));
    expect([...qualitative.querySelectorAll("[data-presentation]")].map((el) => el.textContent ?? "").filter((x) => /\d/.test(x))).toEqual([]);
    // The client re-validates against each kind's contract (UIA-20): out-of-range params never reach a drawing.
    const refused: [string, unknown][] = [
      ["orbital_boxes", { element: "S", charge: 9 }],
      ["maxwell_boltzmann", { temperatures_k: [0], activation_energy_j_mol: 1, energy_max_j_mol: 2 }],
      ["energy_levels", { levels: [{ id: "n1", energy_ev: "-13.6 eV", label: "n = 1" }], transitions: [], show_photon_energy: true }],
      ["born_haber_cycle", { compound: "NaCl", steps: [{ id: "a", kind: "lattice", coefficient: 0, orientation: 1 }], unknown_step: "a" }],
      ["spectrum_chart", { spectrum_id: "x", type: "ultraviolet" }],
      ["reaction_mechanism", { diagram_id: "dgm.bio.heart.v1", sequence_id: "s", step: 0 }],
      ["concentration_time", { mode: "data", species: [], time_unit: "h", concentration_unit: "mol/L", time_range: [0, 1] }],
    ];
    for (const [kind, params] of refused) expect(rendererOf(kind).check(params).length, kind).toBeGreaterThan(0);
  });
});
