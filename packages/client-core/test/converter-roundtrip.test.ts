// Cross-language evidence: the preview must preserve the real worker's expression tree, not just a string fixture.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";
import { convertMath } from "../src/maths-input.js";

test("inp05_converter_round_trip uses the worker grammar", () => {
  const sources = ["2x(x+1)", "\\frac{1}{2}x^2", "2 1/2", "x²+2x+1", "√x", "cbrt(8)", "root(5,x)",
    "frac(a,b)", "sin^2 x", "sin 2x", "log_2(8)", "|x-1|", "0<x<3", "1.2e3", "1.2×10^3", "v_0 t",
    "a_(n-1)", "x^(n+1)", "(x+1)/(x-1)", "x<=2", "x>=2", "x!=2", "theta+pi", "-x^2", "x^2^3",
    "xα+π", "θ²"];
  for (let n = 1; n <= 30; n++) sources.push(`${n}x^2+(${n - 7})x+(${n + 3})`);
  const pairs = sources.map((source) => {
    const result = convertMath(source);
    expect(result.error, source).toBeNull();
    return [source, result.latex];
  });
  const python = fileURLToPath(new URL("../../../.venv/bin/python", import.meta.url));
  const script = `import json,sys\nfrom tool_worker.grammar import parse\nimport sympy as sp\nerrors=[]\nfor source,latex in json.load(sys.stdin):\n try:\n  a,b=parse(source).tree,parse(latex).tree\n  if sp.srepr(a)!=sp.srepr(b): errors.append([source,latex,str(a),str(b)])\n except Exception as e: errors.append([source,latex,str(e)])\nprint(json.dumps(errors))`;
  expect(JSON.parse(execFileSync(python, ["-c", script], { input: JSON.stringify(pairs), encoding: "utf8" }))).toEqual([]);
});
