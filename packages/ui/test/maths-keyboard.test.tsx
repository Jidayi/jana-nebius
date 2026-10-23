import { describe, expect, test } from "vitest";
import { renderTex } from "../src/maths/katex.js";
import { PALETTES, keyFace } from "../src/composer/EntryEditor.js";

// INP-04: the maths keyboard shows each key as maths (alpha as α, dm^3 as dm³, an empty box where the student types),
// never its linear source; units show the unit alone.
describe("maths keyboard key faces", () => {
  const keys = PALETTES.flatMap((p) => p.entries.map((source) => ({ source, mode: p.mode === "chem" && source === "Delta" ? "maths" as const : p.mode })));
  test("every key typesets without an error and shows no linear syntax", () => {
    for (const { source, mode } of keys) {
      const face = keyFace(source, mode);
      expect(renderTex(face, false), `${source} -> ${face}`).not.toHaveProperty("error");
      expect(face, source).not.toContain("□");
      expect(face, source).not.toMatch(/\\text\{/);
      expect(face, source).not.toMatch(/(^|[^\\a-z])(alpha|beta|lambda|sqrt|frac|deg|ohm|->|<=|>=|~=)/);
    }
  });
  test("faces read as a student writes them", () => {
    expect(keyFace("alpha", "maths")).toBe("\\alpha");
    expect(keyFace("□/□", "maths")).toBe("\\square \\div \\square");
    expect(keyFace("□~=□", "maths")).toBe("\\square \\approx \\square");
    expect(keyFace("□ dm^3", "units")).toBe("\\mathrm{dm}^{3}");
    expect(keyFace("□ kg", "units")).toBe("\\mathrm{kg}");
    expect(keyFace("□deg", "maths")).toBe("\\square^{\\circ}");
    expect(keyFace("SO4^2-", "chem")).toBe("\\mathrm{S}\\mathrm{O}_{4}^{2-}");
  });
});

test("keys without their own name are named by what they show", async () => {
  const { faceName } = await import("../src/composer/EntryEditor.js");
  const plain = (source: string, mode: "units" | "chem" | "maths") => faceName(keyFace(source, mode)).replaceAll("\u200b", "");
  expect(["□ dm^3", "□ degC", "□ kohm", "□ um"].map((s) => plain(s, "units"))).toEqual(["dm3", "∘C", "kΩ", "μm"]);
  expect(plain("H2O", "chem")).toBe("H2O");
  expect(plain("alpha", "maths")).toBe("α");
});
