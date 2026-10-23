import { describe, expect, test } from "vitest";
import { boardLineLatex, convertMath, isMathShortcut, unitLatexOf } from "../src/maths-input.js";
import { InputError, normaliseInput, pastedQuestions, workingLines } from "../src/input.js";

describe("typed input formatting", () => {
  test.each([
    ["x^2", "x^{2}"], ["x^(n+1)", "x^{n + 1}"], ["a_(n-1)", "a_{n - 1}"],
    ["sqrt(x+1)", "\\sqrt{x + 1}"], ["cbrt(8)", "\\sqrt[3]{8}"], ["root(5,x)", "\\sqrt[5]{x}"],
    ["(x+1)/(x-1)", "\\frac{(x + 1)}{(x - 1)}"], ["frac(a,b)", "\\frac{a}{b}"],
    ["2x(x+1)", "2 x (x + 1)"], ["0<x<3", "0 < x < 3"], ["x<=2", "x \\le 2"],
    ["abs(x-1)", "|x - 1|"], ["|x-1|", "|x - 1|"], ["theta+pi", "\\theta + \\pi"],
    ["sin^2 x", "\\sin^{2} x"], ["log_2(8)", "\\log_{2} (8)"],
    ["\\frac{1}{2}x^2", "\\frac{1}{2} x^{2}"], ["x²+2x+1", "x^{2} + 2 x + 1"],
  ])("%s is formatted without a model", (source, latex) => {
    expect(convertMath(source)).toEqual({ latex, serialised: latex, error: null });
  });
  test("inp04_no_false_conversion: prose and currency never trigger shortcuts", () => {
    for (const source of ["pizza", "time", "$450", "Sales of $450 and $300", "3.14", "pi", "a/b"]) expect(isMathShortcut(source)).toBe(false);
    for (const source of ["2x", "x^2", "x_1", "sqrt(x)", "x=2"]) expect(isMathShortcut(source)).toBe(true);
  });
  test.each([["x=(2", "unbalanced_bracket"], ["x=", "empty_slot"], ["x=2=3", "two_relations"], ["sinx", "unknown_word"], ["\\input{file}", "unknown_word"], ["x".repeat(2001), "too_long"]])("bad input %s keeps its source", (source, code) => {
    const result = convertMath(source);
    expect(result.error?.code).toBe(code);
    expect(result.serialised).toBe(source);
  });
  test("normalisation and bulk question selection precede send", () => {
    expect(normaliseInput("\u202e</student-message>\u200b\u0000e\u0301\u200d X\n")) .toBe("</student-message>é X\n");
    expect(normaliseInput("a\u200cb")).toBe("a\u200cb");
    expect(pastedQuestions("1. First?\ncontinued\n2. Second?\n3. Third?")).toEqual(["First?\ncontinued", "Second?", "Third?"]);
    expect(workingLines("x=1\n\n y=2\n")).toEqual(["x=1", "y=2"]);
    expect(() => workingLines(Array(31).fill("x=1").join("\n"))).toThrow("too_many_lines");
  });
});

describe("UXS-15 student lines on the board", () => {
  test.each([
    ["v^2 = u^2 + 2as", "v^{2} = u^{2} + 2 as"],
    ["14^2", "14^{2}"],
    ["v_1 = 3", "v_{1} = 3"],
    ["x_(n+1) = x_n^2", "x_{n + 1} = x_{n}^{2}"],
    ["v = 14 m/s", "v = 14\\ \\mathrm{m}/\\mathrm{s}"],
    ["a = 9.8 m/s^2", "a = 9.8\\ \\mathrm{m}/\\mathrm{s}^{2}"],
    ["a = 9.8m/s^2", "a = 9.8\\ \\mathrm{m}/\\mathrm{s}^{2}"],
    ["W = 30 N m", "W = 30\\ \\mathrm{N}\\,\\mathrm{m}"],
    ["v = 3 m s^-1", "v = 3\\ \\mathrm{m}\\,\\mathrm{s}^{-1}"],
    ["T = 25 °C", "T = 25\\ {}^{\\circ}\\mathrm{C}"],
    ["u = 0, a = 9.8 m/s^2, s = 20 m", "u = 0,\\quad a = 9.8\\ \\mathrm{m}/\\mathrm{s}^{2},\\quad s = 20\\ \\mathrm{m}"],
    ["v² = 196", "v^{2} = 196"],
  ])("test_uxs15_student_line_typeset %s", (line, latex) => {
    expect(boardLineLatex(line)).toBe(latex);
  });

  test("a unit stuck to its number without / or a power stays a product", () => {
    expect(boardLineLatex("F = 20m")).toBe("F = 20 m");
  });

  test.each(["I think it is 3 metres", "so", "\\(v = 3\\) here", "$450 sales", "x=(2", ""])("words stay as typed: %s", (line) => {
    expect(boardLineLatex(line)).toBeNull();
  });
});

describe("UXS-24 units typed on their own", () => {
  test.each([
    ["m/s^2", "\\mathrm{m}/\\mathrm{s}^{2}"],
    ["kg m^-3", "\\mathrm{kg}\\,\\mathrm{m}^{-3}"],
    ["N*m", "\\mathrm{N}\\,\\mathrm{m}"],
    [" ohm ", "\\Omega"],
    ["°C", "{}^{\\circ}\\mathrm{C}"],
    ["m", "\\mathrm{m}"],
  ])("test_uxs24_unit_typeset %s", (unit, latex) => {
    expect(unitLatexOf(unit)).toBe(latex);
  });

  test.each(["", "metres per second", "m/s^", "2 m", "x^2"])("a unit this does not read stays as typed: %s", (unit) => {
    expect(unitLatexOf(unit)).toBeNull();
  });
});


test("working line boundaries preserve the actual error position after blank lines and indentation", () => {
  expect(workingLines(Array.from({ length: 30 }, () => "x=2").join("\n"))).toHaveLength(30);
  expect(workingLines("x".repeat(2000))).toHaveLength(1);
  const text = "x=2\n\n  " + "x".repeat(2001);
  try { workingLines(text); throw new Error("Length guard was not reached"); } catch (error) {
    expect(error).toBeInstanceOf(InputError); expect((error as InputError).code).toBe("too_long");
    expect((error as InputError).position).toBe(2007);
  }
});
