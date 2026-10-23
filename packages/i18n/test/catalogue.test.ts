// LOC-02 (parity), LOC-03 (plural branches), LOC-04 (pseudo-locale) and UXS-05 (copy lint) over the catalogues.
import { describe, expect, test } from "vitest";
import { BASE, PSEUDO, SHIPPED, argumentsOf, catalogue, copyLintErrors, parityErrors, pluralErrors, translator } from "../src/index.js";

const ALL = [...SHIPPED, ...PSEUDO];

function sampleArgs(message: string, count: number): Record<string, string | number> {
  const args: Record<string, string | number> = {};
  for (const [name, type] of Object.entries(argumentsOf(message))) args[name] = type === "string" || type === "select" ? "x" : count;
  return args;
}

describe("LOC-02", () => {
  test("loc02_locale_parity", () => {
    for (const locale of ALL) expect(parityErrors(BASE, locale, catalogue(locale))).toEqual([]);
  });
});

describe("LOC-03", () => {
  test("loc03_plural_branches", () => {
    for (const locale of ALL) {
      expect(pluralErrors(locale === "en-XA" ? "en" : locale, catalogue(locale))).toEqual([]);
      const t = translator(locale);
      for (const [key, message] of Object.entries(catalogue(locale))) {
        if (!Object.values(argumentsOf(message)).includes("plural")) continue;
        for (const count of [0, 1, 2, 5, 11, 100]) {
          const out = t(key, sampleArgs(message, count));
          expect(out).not.toBe(key);
          expect(out).toContain(new Intl.NumberFormat("en").format(count));
        }
      }
    }
  });
});

describe("LOC-04", () => {
  test("every key formats in the pseudo-locale, accented, padded and bracketed", () => {
    const t = translator("en-XA");
    const en = translator("en");
    for (const [key, message] of Object.entries(BASE)) {
      if (message === "") continue;
      const out = t(key, sampleArgs(message, 3));
      expect(out.startsWith("[") && out.endsWith("]")).toBe(true);
      expect(out.length).toBeGreaterThanOrEqual(Math.floor(en(key, sampleArgs(message, 3)).length * 1.3));
    }
  });
});

describe("UXS-05", () => {
  test("uxs05_copy_lint", () => {
    expect(copyLintErrors(BASE)).toEqual([]);
    expect(copyLintErrors({ "file.help": "Choose a PDF, JPEG or PNG file." })).toEqual([]);
    // The linter itself catches each rule.
    expect(copyLintErrors({ "a.b": "GREAT JOB", "tutor.feedback": "That is wrong", "x.y": "Saved!" })).toHaveLength(3);
  });
});
