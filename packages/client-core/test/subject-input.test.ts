import unitGoldens from "../../ui/gallery/unit-entry-golden.json";
import goldens from "../../ui/gallery/chem-entry-golden.json";
import { expect, test } from "vitest";
import { convertEntry } from "../src/subject-input.js";

test.each([
  ["2H2 + O2 -> 2H2O", "2H2 + O2 -> 2H2O", "2\\mathrm{H}_{2} + \\mathrm{O}_{2} \\rightarrow 2\\mathrm{H}_{2}\\mathrm{O}"],
  ["CuSO4.5H2O", "CuSO4·5H2O", "\\mathrm{Cu}\\mathrm{S}\\mathrm{O}_{4}\\cdot 5\\mathrm{H}_{2}\\mathrm{O}"],
  ["SO4^2-(aq)", "SO4^2-(aq)", "\\mathrm{S}\\mathrm{O}_{4}^{2-}\\mathrm{(aq)}"],
  ["Ca(OH)2", "Ca(OH)2", "\\mathrm{Ca}(\\mathrm{O}\\mathrm{H})_{2}"],
  ["CaCO3(s) ->[heat] CaO(s) + CO2(g)", "CaCO3(s) ->[heat] CaO(s) + CO2(g)", "\\mathrm{Ca}\\mathrm{C}\\mathrm{O}_{3}\\mathrm{(s)} \\xrightarrow{\\mathrm{heat}} \\mathrm{Ca}\\mathrm{O}\\mathrm{(s)} + \\mathrm{C}\\mathrm{O}_{2}\\mathrm{(g)}"],
])("chemistry renders %s and preserves its grammar", (source, serialised, latex) => {
  expect(convertEntry(source, "chem")).toEqual({ latex, serialised, error: null });
});

test.each(["9.8 m/s^2", "0.5 mol dm^-3", "25 degC", "4.7 kohm"])("units retain the magnitude of %s", (source) => {
  const result = convertEntry(source, "units");
  expect(result.error).toBeNull();
  expect(result.latex).toContain("\\mathrm{");
  expect(result.serialised.split(" ")[0]).toBe(source.split(" ")[0]);
});

test("subject input never silently fixes case or converts values", () => {
  expect(convertEntry("Co", "chem").latex).not.toBe(convertEntry("CO", "chem").latex);
  expect(convertEntry("co", "chem").error?.code).toBe("unknown_element");
  expect(convertEntry("25 deg C", "units").serialised).toBe("25 °C");
  expect(convertEntry("4.7 kohm", "units").serialised).toBe("4.7 kΩ");
  expect(convertEntry("3 um", "units").serialised).toBe("3 µm");
  expect(convertEntry("5 C", "units").error?.code).toBe("ambiguous_unit");
});


test.each(goldens)("inp08_chem_entry_golden: $id", ({ source, serialised, latex }) => {
  expect(convertEntry(source, "chem")).toEqual({ latex, serialised, error: null });
  expect(convertEntry(serialised, "chem")).toEqual({ latex, serialised, error: null });
});

for (const mode of ["maths", "units"] as const) test.each(unitGoldens)(`inp09_units_golden: ${mode} $id`, ({ source, serialised, latex }) => {
  expect(convertEntry(source, mode)).toEqual({ latex, serialised, error: null });
});

test("quantity recognition never steals algebra identifiers or resolves ambiguous C", () => {
  for (const source of ["3 x", "3 mmx", "3 k"]) expect(convertEntry(source).latex).not.toContain("\\mathrm");
  expect(convertEntry("25 C").error).toMatchObject({ code: "ambiguous_unit", position: 3 });
  expect(convertEntry("3 bananas", "units").serialised).toBe("3 bananas"); // the worker owns unit validity
});
