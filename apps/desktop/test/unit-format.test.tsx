import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { PSEUDO, SHIPPED, formatDate, formatTime, translator, type Locale } from "@jana/i18n";
import { boardLineLatex, convertEntry } from "@jana/client-core";
import { LocaleProvider } from "../../../packages/ui/src/i18n.js";
import { Tex } from "../../../packages/ui/src/maths/Tex.js";
import { PackText } from "../../../packages/ui/src/learn/PackText.js";

afterEach(cleanup);
test.each([...SHIPPED, ...PSEUDO])("loc10_unit_format: %s", (locale: Locale) => {
  for (const text of ["9.8 m/s^2", "3 kg m^-3", "25 °C", "1.00 mol"]) {
    const converted = convertEntry(text, "units"); expect(converted.error).toBeNull();
    expect(converted.serialised).toBe(text);
    expect(converted.latex).toMatch(/\d(?:\.\d+)?\\,/);
    const { container } = render(<LocaleProvider locale={locale}><Tex tex={converted.latex} /></LocaleProvider>);
    expect(container.querySelector("math mtext")?.textContent).toBe("\u2009");
    expect(container.querySelector(".katex-html .mspace")).not.toBeNull();
    expect(container.querySelector("annotation")?.textContent).toBe(converted.latex);
    expect(container.textContent).not.toContain("9,8"); cleanup();
  }
  expect(boardLineLatex("a = 9.8 m/s^2")).toBe("a = 9.8\\ \\mathrm{m}/\\mathrm{s}^{2}");
  const text = "Use a speed of 9.8 m/s and \\(a=9.8\\,\\mathrm{m/s^2}\\).";
  const { container } = render(<LocaleProvider locale={locale}><PackText text={text} /></LocaleProvider>);
  expect(container.textContent).toContain("9.8 m/s");
  expect(container.querySelector("annotation")?.textContent).toBe("a=9.8\\,\\mathrm{m/s^2}");
  expect(text).not.toContain("9,8");
  const date = new Date(2026, 9, 8, 15, 5);
  expect(formatDate(date, locale)).toBe("8 October 2026");
  expect(formatDate(date.toISOString(), locale)).toBe("8 October 2026");
  expect(formatTime(date.toISOString(), locale)).toBe(formatTime(date, locale));
  expect(formatDate(date, locale, true)).toBe("08/10/2026");
  expect(formatTime(date, locale)).toMatch(/3:05\s*pm/i);
  const t = translator(locale);
  expect(t("ledger.at", { at: date })).toContain("8 October 2026");
  expect(t("ledger.at", { at: date })).toMatch(/3:05\s*pm/i);
});
