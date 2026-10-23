// Every reasonable way a student types the same notation reads back the same (polish pass): standard form, unit
// powers as superscripts, degrees, subscript digits, and ion charges typed without "^".
import { expect, test } from "vitest";
import { boardLineLatex, convertEntry, convertMath, unitLatexOf } from "../src/index.js";

test.each(["3.2e-4", "3.2E-4", "3.2x10^-4", "3.2 X 10^(-4)", "3.2*10^-4", "3.2*10**-4", "3.2×10⁻⁴", "3.2 \\times 10^{-4}"])(
  "standard form %s reads as 3.2 × 10⁻⁴", (typed) => {
    expect(convertMath(typed).latex).toBe("{3.2 \\times 10^{-4}}");
    expect(boardLineLatex(typed)).toBe("{3.2 \\times 10^{-4}}");
  });

test("a times sign only becomes standard form before a power of ten: algebra stays algebra", () => {
  expect(convertMath("2x+3").latex).toBe("2 x + 3");
  expect(convertMath("e^x").latex).toBe("e^{x}");
});

test("degrees, subscripts and superscript powers", () => {
  expect(convertMath("30°").latex).toBe("30^{\\circ}");
  expect(convertMath("x₁ + x₂").latex).toBe("x_{1} + x_{2}");
  expect(convertMath("x²+3x").latex).toBe("x^{2} + 3 x");
  expect(boardLineLatex("a = 9.8 m/s²")).toBe("a = 9.8\\ \\mathrm{m}/\\mathrm{s}^{2}");
  expect(boardLineLatex("v = 3.0x10^8 m/s")).toBe("v = {3.0 \\times 10^{8}}\\ \\mathrm{m}/\\mathrm{s}");
});

test.each([["m/s²", "m/s^2"], ["mol dm⁻³", "mol dm^-3"], ["degC", "°C"]])("unit %s reads as %s", (typed, plain) => {
  expect(unitLatexOf(typed)).toBe(unitLatexOf(plain));
  expect(unitLatexOf(typed)).not.toBeNull();
});

test.each([["6.02x10^23 mol^-1"], ["6.02×10²³ mol⁻¹"], ["6.02e23 mol^-1"]])("a quantity in standard form: %s", (typed) => {
  expect(convertEntry(typed, "units").latex).toBe("6.02 \\times 10^{23}\\,\\mathrm{mol}^{-1}");
});

test.each([["Fe3+", "\\mathrm{Fe}^{3+}"], ["Fe³⁺", "\\mathrm{Fe}^{3+}"], ["Na+", "\\mathrm{Na}^{+}"], ["Cl-", "\\mathrm{Cl}^{-}"],
  ["H₂SO₄", "\\mathrm{H}_{2}\\mathrm{S}\\mathrm{O}_{4}"], ["Fe3+(aq)", "\\mathrm{Fe}^{3+}\\mathrm{(aq)}"],
  ["Cu2+ + 2e- -> Cu", "\\mathrm{Cu}^{2+} + 2\\mathrm{e}^{-} \\rightarrow \\mathrm{Cu}"],
  ["2H2 + O2 -> 2H2O", "2\\mathrm{H}_{2} + \\mathrm{O}_{2} \\rightarrow 2\\mathrm{H}_{2}\\mathrm{O}"]])("chemistry %s", (typed, latex) => {
  expect(convertEntry(typed, "chem").latex).toBe(latex);
});

test("units mode (a physics entry): a unit alone is upright, anything else not a quantity is maths", () => {
  expect(convertEntry("3.2x10^-4", "units").latex).toBe("{3.2 \\times 10^{-4}}");
  expect(convertEntry("dm^-3", "units").latex).toBe("\\mathrm{dm}^{-3}");
  expect(convertEntry("9.8 m/s^2", "units").latex).toBe("9.8\\,\\mathrm{m}/\\mathrm{s}^{2}");
  expect(convertEntry("v^2", "units").latex).toBe("v^{2}"); // neither a quantity nor a unit: ordinary maths
});
