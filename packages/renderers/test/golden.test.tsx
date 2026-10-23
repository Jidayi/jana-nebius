// @vitest-environment happy-dom
// Golden renders and fuzzing (VSL-35): every kind fixture, preset and library entry is rendered in the light and dark
// themes and at 150 % text, with token colours resolved, and compared with its reviewed golden file; a difference
// fails until a reviewer accepts it (UPDATE_GOLDEN=1 rewrites the files for review in the change). Spec fuzzing
// mutates valid specs and generates params from each kind's schema; nothing may crash. The nightly run sets
// JANA_FUZZ_RUNS higher than the per-commit default.
import { describe, expect, test } from "vitest";
import type { ResolvedSpec } from "../src/index.js";
import { draw, fixtures, lineDiff, readGolden, rendererOf, variants, writeGolden } from "./helpers.js";

const ALL = fixtures();
const UPDATE = process.env.UPDATE_GOLDEN === "1";
const RUNS = Number(process.env.JANA_FUZZ_RUNS ?? 40);

describe("VSL-35", () => {
  test("golden renders match in light, dark and 150% text", () => {
    const differences: string[] = [];
    for (const f of ALL) {
      for (const [variant, text] of Object.entries(variants(f.spec))) {
        const golden = readGolden(f.id, variant);
        if (UPDATE || golden === null) {
          writeGolden(f.id, variant, text);
          if (!UPDATE) differences.push(`${f.id}.${variant}: no golden render yet (written for review)`);
          continue;
        }
        const diff = lineDiff(golden, text);
        if (diff.length > 0) differences.push(`${f.id}.${variant}:\n${diff.slice(0, 12).join("\n")}`);
      }
    }
    expect(differences).toEqual([]);
  });

  test("vsl35_golden_diff", () => {
    const heart = ALL.find((f) => f.id === "library-heart")!;
    const golden = readGolden(heart.id, "light");
    expect(golden).not.toBeNull();
    const svg = (heart.spec.computed as { svg: string }).svg;
    expect(svg).toContain('x="135"');
    // Move the vena cava one pixel to the right.
    const moved = { ...heart.spec, computed: { ...heart.spec.computed, svg: svg.replace('x="135"', 'x="136"') } } as unknown as ResolvedSpec;
    const diff = lineDiff(golden!, variants(moved).light);
    expect(diff.length).toBeGreaterThan(0);
    expect(diff.length).toBeLessThanOrEqual(4);
    expect(diff.join("\n")).toContain('x="136"');
    expect(diff.join("\n")).toContain('x="135"');
    // The unchanged drawing still matches.
    expect(lineDiff(golden!, variants(heart.spec).light)).toEqual([]);
  });
});

/** A small deterministic generator (the same seed gives the same run). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), a | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function mutate(value: unknown, r: () => number, depth = 0): unknown {
  const junk = [null, -1, 0, 1e9, "", "x", "-inf", [], {}, true, "<script>", NaN, "9999999999999"];
  if (r() < 0.12) return junk[Math.floor(r() * junk.length)];
  if (Array.isArray(value)) {
    const out = value.map((v) => mutate(v, r, depth + 1));
    if (r() < 0.2) out.pop();
    if (r() < 0.1 && out.length > 0) out.push(out[0]);
    return out;
  }
  if (value !== null && typeof value === "object" && depth < 6) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) if (r() > 0.08) out[k] = mutate(v, r, depth + 1);
    return out;
  }
  if (typeof value === "number") return r() < 0.3 ? value * (r() * 4 - 2) : value;
  return value;
}

describe("VSL-35 fuzzing", () => {
  test("mutated specs never crash a renderer: valid ones draw, invalid ones are caught by the client check", () => {
    let drawn = 0;
    let refused = 0;
    for (const f of ALL) {
      const R = rendererOf(f.kind);
      for (let n = 0; n < RUNS; n += 1) {
        const r = rng(n * 7919 + f.id.length);
        const params = mutate(f.spec.params, r);
        const spec = { ...f.spec, params } as unknown as ResolvedSpec;
        if (R.check(params).length > 0) {
          refused += 1;
          continue;
        }
        // A spec that passes the client check draws, or its renderer shows the words fallback; it never throws.
        expect(() => draw(spec), `${f.id} run ${n}`).not.toThrow();
        drawn += 1;
      }
    }
    expect(drawn).toBeGreaterThan(0);
    expect(refused).toBeGreaterThan(0);
  });
});
