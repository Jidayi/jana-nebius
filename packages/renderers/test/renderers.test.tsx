// @vitest-environment happy-dom
// VSL-16 (fallback ladder under fuzz), VSL-18 (pure, deterministic renderers) and the SVG half of SEC-11.
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { RENDERERS, type ResolvedSpec } from "../src/index.js";

const graph = RENDERERS.find((r) => r.kind === "function_graph")!;

function spec(params: unknown, extra: Partial<ResolvedSpec> = {}): ResolvedSpec {
  return {
    spec_version: 1, type: "function_graph", params: params as ResolvedSpec["params"], numbers_from: [], steps: [], labels: "shown",
    visual_id: `vis_${"0".repeat(26)}`, status: "ok", parts: [], alt: { summary: "A curve.", steps: [], locale: "en" }, computed: {}, repairs: [],
    ...extra,
  } as ResolvedSpec;
}

function draw(s: ResolvedSpec): string {
  return renderToStaticMarkup(<graph.Component spec={s} step={0} labels="shown" focus={[]} size={{ width: 480, height: 320 }} reducedMotion={false} onPartActivate={() => undefined} />);
}

describe("VSL-18", () => {
  test("vsl18_renderer_imports_pure", () => {
    const forbidden = /from\s+["'](node:|fs|http|https|net|axios|ky|undici|openai|@anthropic-ai|localforage|idb)|\bfetch\(|XMLHttpRequest|WebSocket|localStorage|sessionStorage|indexedDB|\beval\(|new Function\(|dangerouslySetInnerHTML/;
    const dir = path.resolve(import.meta.dirname, "../src");
    const walk = (d: string): string[] => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]));
    const files = walk(dir).filter((f) => /\.tsx?$/.test(f));
    expect(files.length).toBeGreaterThan(10);
    for (const full of files) {
      const file = path.relative(dir, full);
      const text = fs.readFileSync(full, "utf8");
      expect(forbidden.test(text), file).toBe(false);
      // Only React, the contracts and the package's own modules (its generated data and schemas included).
      for (const m of text.matchAll(/from\s+["']([^"']+)["']/g)) expect(["react", "@jana/contracts-ts", "@jana/contracts-ts/client"].includes(m[1]!) || m[1]!.startsWith("./") || m[1]!.startsWith("../"), `${file} imports ${m[1]}`).toBe(true);
      for (const m of text.matchAll(/from\s+["'](\.\.?\/[^"']+)["']/g)) expect(path.resolve(path.dirname(full), m[1]!).startsWith(dir), `${file} imports outside the package: ${m[1]}`).toBe(true);
    }
  });

  test("vsl18_render_deterministic", () => {
    const s = spec({ curves: [{ id: "h", expr: "14*t - 4.9*t^2", label: "height" }, { id: "g", expr: "sin(x)", style: "dashed" }], x_range: [0, 3], points: [{ id: "P", x: 1.43, y: 10, label: "peak" }] });
    expect(draw(s)).toBe(draw(s));
    expect(draw(s)).toContain("<svg");
  });
});

describe("VSL-16", () => {
  function fuzz(seed: number): unknown {
    let a = seed;
    const r = () => ((a = (a * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
    const pick = <T,>(xs: T[]) => xs[Math.floor(r() * xs.length)]!;
    const junk = () => pick<unknown>([null, 1, "x", [], {}, "14*t -* 4", "sin(", "1/0", "x^x^x^x", "a".repeat(300), -1e308, NaN, "eval(1)", "constructor"]);
    return {
      curves: pick<unknown>([[], junk(), [{ id: junk(), expr: junk() }], [{ id: "a", expr: pick(["x", "1/x", "sqrt(x)", "log(x)", "tan(x)", junk()]) }]]),
      x_range: pick<unknown>([[0, 1], [5, -5], [0, 0], junk(), [NaN, 1], [-1e9, 1e9]]),
      y_range: pick<unknown>([undefined, [0, 1], [1, 1], junk()]),
      points: pick<unknown>([undefined, [{ id: "P", x: junk(), y: junk() }], junk()]),
    };
  }

  test("vsl16_fuzz_never_crashes", () => {
    let drawn = 0;
    let words = 0;
    for (let n = 0; n < 10_000; n += 1) {
      let html: string;
      try {
        html = draw(spec(fuzz(n + 1)));
      } catch {
        // A spec the renderer cannot read falls back to words (the client's ladder, VSL-16).
        html = renderToStaticMarkup(<graph.Fallback spec={spec(fuzz(n + 1))} reason="render_failed" />);
      }
      if (html.includes("<svg")) drawn += 1;
      else if (html.includes("A curve.")) words += 1;
      else throw new Error(`no rung for seed ${n + 1}: ${html.slice(0, 80)}`);
    }
    expect(drawn + words).toBe(10_000);
    expect(drawn).toBeGreaterThan(0);
    expect(words).toBeGreaterThan(0);
  });

  test("the text-only rung shows the words, never empty axes", () => {
    const html = draw(spec({ curves: [{ id: "h", expr: "14*t -* 4.9" }], x_range: [0, 3] }, { status: "text_only" }));
    expect(html).not.toContain("<svg");
    expect(html).toContain("A curve.");
  });
});

describe("SEC-11", () => {
  test("sec11_xss_payloads_inert (visual specs)", () => {
    const payloads = ['<script>alert(1)</script>', 'javascript:alert(1)', '" onload="alert(1)', "<svg onload=alert(1)>", "<foreignObject><iframe/></foreignObject>"];
    for (const p of payloads) {
      const html = draw(spec({ curves: [{ id: "h", expr: "x", label: p }], x_range: [0, 1], axis_labels: { x: p, y: p }, points: [{ id: "P", x: 0.5, y: 0.5, label: p }] }, { alt: { summary: p, steps: [], locale: "en" } }));
      const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
      expect(doc.querySelector("script, iframe, foreignObject, foreignobject, [href], [xlink\\:href]")).toBeNull();
      for (const el of doc.querySelectorAll("*")) for (const attr of el.attributes) expect(attr.name.startsWith("on"), `${el.tagName} ${attr.name}`).toBe(false);
    }
  });
});
