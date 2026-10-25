// DSN-01 to DSN-03, DSN-07 to DSN-14 and LOC-01: the design governance tests, on the real sources and on seeded
// violations.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { BASE } from "@jana/i18n";
import { TOKENS } from "../src/generated/tokens.js";
import {
  dangerErrors, dockErrors, iconErrors, keyErrors, literalStringErrors, monopolyErrors, motionErrors, radiusErrors, rawColourErrors,
  sizeErrors, sources, weightCapsErrors, zIndexErrors, type Source,
} from "./governance.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");
const files = sources();
const seed = (p: string, text: string): Source[] => [{ path: p, text }];

describe("DSN-01", () => {
  test("dsn01_generated_tokens_fresh", () => {
    const contract = fs.readFileSync(path.join(ROOT, "packages/ui/tokens.json"));
    const digest = crypto.createHash("sha256").update(contract).digest("hex");
    for (const name of ["tokens.css", "theme.css", "tokens.ts"]) {
      expect(fs.readFileSync(path.join(import.meta.dirname, "../src/generated", name), "utf8")).toContain(`source sha256: ${digest}`);
    }
  });

  test("dsn01_no_seed_in_components", () => {
    expect(rawColourErrors(files)).toEqual([]);
    expect(fs.readFileSync(path.join(import.meta.dirname, "../src/generated/tokens.css"), "utf8")).not.toMatch(/seed/);
  });
});

describe("DSN-02", () => {
  const ROLES = [
    "canvas", "paper", "panel", "chrome", "line", "line-strong", "scrim", "ink", "muted", "faint", "placeholder",
    "accent", "accent-ink", "accent-soft", "accent-hover",
    // D89: ink primary actions, the neutral selected/hover wash, brand-moment midnight, the logo's two panels.
    "action", "action-hover", "action-ink", "wash",
    "midnight", "midnight-raised", "midnight-line", "on-midnight", "on-midnight-muted", "brand-stem", "brand-hook",
    ...["verified", "hint", "misconception", "highlight"].flatMap((r) => [r, `${r}-soft`, `${r}-line`]),
    ...["not-started", "learning", "nearly", "secure", "refresh", "moved-on"].flatMap((m) => [`mastery-${m}`, `mastery-${m}-ink`]),
    ...Array.from({ length: 8 }, (_, i) => `avatar-${i + 1}`), "avatar-ink", "student", "tutor",
    "danger", "danger-soft", "warn", "warn-soft", "info", "info-soft", "focus",
  ];

  test("dsn02_roles_complete", () => {
    const colours = TOKENS.color as Record<string, { light?: string; dark?: string }>;
    for (const role of ROLES) {
      expect(colours[role]?.light, role).toBeTruthy();
      expect(colours[role]?.dark, role).toBeTruthy();
    }
  });

  test("dsn02_no_danger_in_learning", () => {
    expect(dangerErrors(files)).toEqual([]);
  });
});

function luminance(colour: string): number {
  const hex = colour.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function composite(colour: string, over: string): string {
  const rgba = /rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/.exec(colour);
  if (rgba === null) return colour;
  const base = [0, 2, 4].map((i) => parseInt(over.replace("#", "").slice(i, i + 2), 16));
  const alpha = Number(rgba[4]);
  return `#${[1, 2, 3].map((k, i) => Math.round(Number(rgba[k]) * alpha + base[i]! * (1 - alpha)).toString(16).padStart(2, "0")).join("")}`;
}

function ratio(a: string, b: string): number {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1! + 0.05) / (l2! + 0.05);
}

describe("DSN-03", () => {
  test("dsn03_token_contrast", () => {
    const colours = TOKENS.color as Record<string, { light: string; dark: string; contrast?: { required: number; against: string[]; minLight: number; minDark: number } }>;
    let checked = 0;
    for (const [name, token] of Object.entries(colours)) {
      if (token.contrast === undefined) continue;
      for (const theme of ["light", "dark"] as const) {
        const lowest = Math.min(...token.contrast.against.map((surface) => {
          const back = colours[surface]![theme];
          return ratio(composite(token[theme], back), back);
        }));
        expect(lowest, `${name} ${theme}`).toBeGreaterThanOrEqual(token.contrast.required);
        const recorded = theme === "light" ? token.contrast.minLight : token.contrast.minDark;
        expect(Math.abs(lowest - recorded), `${name} ${theme} recorded ${recorded}, computed ${lowest.toFixed(3)}`).toBeLessThanOrEqual(0.01);
        checked += 1;
      }
    }
    expect(checked).toBeGreaterThan(40);
  });
});

/** The `--color-*` values of one theme block of the generated stylesheet the app imports (`styles/ui.css`). */
function themeColours(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...block.matchAll(/--color-([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.trim()]));
}

describe("DSN-24", () => {
  test("dsn24_avatar_contrast", () => {
    const css = fs.readFileSync(path.join(import.meta.dirname, "../src/generated/tokens.css"), "utf8");
    expect(fs.readFileSync(path.join(import.meta.dirname, "../src/styles/ui.css"), "utf8")).toContain('@import "../generated/tokens.css"');
    const discs = Array.from({ length: 8 }, (_, i) => `avatar-${i + 1}`);
    const lowest: Record<string, number> = {};
    for (const [theme, selector] of [["light", ":root"], ["dark", '[data-theme="dark"]']] as const) {
      const colours = themeColours(css, selector);
      const ink = colours["avatar-ink"]!;
      expect(ink, theme).toMatch(/^#[0-9A-Fa-f]{6}$/);
      // The stylesheet the app uses carries the contract's values.
      expect(ink).toBe((TOKENS.color as Record<string, Record<string, string>>)["avatar-ink"]![theme]);
      const ratios = discs.map((disc) => {
        const fill = colours[disc]!;
        expect(fill, `${disc} ${theme}`).toBe((TOKENS.color as Record<string, Record<string, string>>)[disc]![theme]);
        const r = ratio(ink, fill);
        expect(r, `avatar-ink on ${disc} (${theme})`).toBeGreaterThanOrEqual(4.5);
        return r;
      });
      lowest[theme] = Math.min(...ratios);
    }
    // The figures DSN-24 states for the lowest disc: 6.06 light, 9.05 dark (D89 moved avatar-ink to the ink family).
    expect(lowest.light).toBeCloseTo(6.06, 2);
    expect(lowest.dark).toBeCloseTo(9.05, 2);
    // The avatar component draws exactly these: the initial in avatar-ink on one of the eight discs.
    const avatar = fs.readFileSync(path.join(import.meta.dirname, "../src/profiles/Avatar.tsx"), "utf8");
    expect(avatar).toContain("text-avatar-ink");
    for (const disc of discs) expect(avatar).toContain(`"bg-${disc}"`);
    expect(avatar).not.toMatch(/bg-(?!avatar-)[a-z]/);
  });
});

describe("DSN-07 to DSN-13", () => {
  test("dsn07_named_sizes_only", () => expect(sizeErrors(files)).toEqual([]));
  test("dsn08_radius_from_tokens", () => {
    expect(radiusErrors(files)).toEqual([]);
    // Elevation: stacking levels come only from the zIndex tokens, and the Tailwind theme carries each of them, so
    // `z-popover` is a real class rather than one Tailwind silently drops.
    expect(zIndexErrors(files)).toEqual([]);
    expect(dockErrors(files)).toEqual([]);
    expect(files.some((f) => f.path.endsWith("primitives/ComposerShell.tsx") && /shadow-dock/.test(f.text) && /rounded-composer/.test(f.text))).toBe(true);
    const theme = fs.readFileSync(path.join(import.meta.dirname, "../src/generated/theme.css"), "utf8");
    for (const level of Object.keys(TOKENS.zIndex)) expect(theme, level).toContain(`--z-index-${level}: var(--z-${level});`);
  });
  test("dsn09_motion_contract", () => expect(motionErrors(files).filter((e) => !e.includes("keyframes"))).toEqual([]));
  test("dsn10_primitives_only", () => expect(motionErrors(files)).toEqual([]));
  test("dsn11_icon_map_unique", () => expect(iconErrors(files)).toEqual([]));
  test("dsn12_primitive_monopoly", () => expect(monopolyErrors(files)).toEqual([]));
  test("test_dsn13_no_raw_hex", () => expect(rawColourErrors(files)).toEqual([]));
  test("test_dsn13_no_numeric_weight_or_caps", () => expect(weightCapsErrors(files)).toEqual([]));

  test("dsn13_governance_seeded_violations", () => {
    expect(rawColourErrors(seed("packages/ui/src/x.tsx", 'const c = "#1A1C19";'))).not.toEqual([]);
    expect(rawColourErrors(seed("packages/ui/src/x.css", "a { color: rgb(1, 2, 3); }"))).not.toEqual([]);
    expect(radiusErrors(seed("packages/ui/src/x.tsx", '<div className="rounded-lg" />'))).not.toEqual([]);
    expect(radiusErrors(seed("packages/ui/src/x.tsx", '<div className="p-[13px]" />'))).not.toEqual([]);
    expect(dockErrors(seed("packages/ui/src/board/x.tsx", '<div className="rounded-card shadow-dock" />'))).not.toEqual([]);
    expect(zIndexErrors(seed("packages/ui/src/x.tsx", '<div className="fixed z-50" />'))).not.toEqual([]);
    expect(zIndexErrors(seed("packages/ui/src/x.tsx", 'const look = open ? "absolute md:z-[60]" : "";'))).not.toEqual([]);
    expect(zIndexErrors(seed("packages/ui/src/x.tsx", "<div style={{ zIndex: 5 }} />"))).not.toEqual([]);
    expect(zIndexErrors(seed("packages/ui/src/x.css", ".a { z-index: 999; }"))).not.toEqual([]);
    expect(zIndexErrors(seed("packages/ui/src/x.tsx", '<div className="fixed z-dialog" />'))).toEqual([]);
    expect(zIndexErrors(seed("packages/ui/src/x.css", ".a { z-index: var(--z-toast); }"))).toEqual([]);
    expect(sizeErrors(seed("packages/ui/src/x.tsx", '<p className="text-[15px]" />'))).not.toEqual([]);
    expect(weightCapsErrors(seed("packages/ui/src/x.tsx", '<p className="font-bold uppercase" />'))).toHaveLength(2);
    expect(motionErrors(seed("packages/ui/src/x.css", "@keyframes spin { to { opacity: 0 } }"))).not.toEqual([]);
    expect(motionErrors(seed("packages/ui/src/x.tsx", '<div className="transition-all" />'))).not.toEqual([]);
    expect(motionErrors(seed("packages/ui/src/primitives/motion.css", "@keyframes a {}"))).not.toEqual([]);
    expect(iconErrors(seed("packages/ui/src/x.tsx", 'import { Check } from "lucide-react";'))).not.toEqual([]);
    expect(iconErrors(seed("packages/ui/src/icons.tsx", "a: { glyph: Check }, b: { glyph: Check }"))).not.toEqual([]);
    expect(monopolyErrors(seed("packages/ui/src/x.tsx", '<button title="Send" />'))).not.toEqual([]);
    expect(monopolyErrors(seed("packages/ui/src/x.tsx", '<Button title="Send" />'))).not.toEqual([]);
    expect(monopolyErrors(seed("packages/ui/src/x.tsx", '<StudyCitations title={() => sourceTitle} />'))).toEqual([]);
    expect(monopolyErrors(seed("packages/ui/src/x.tsx", '<><svg><title>Chart</title></svg><button title={label} /></>'))).not.toEqual([]);
    expect(monopolyErrors(seed("packages/ui/src/x.tsx", '<div role="alertdialog" />'))).not.toEqual([]);
    expect(dangerErrors(seed("packages/ui/src/board/x.tsx", '<p className="text-danger" />'))).not.toEqual([]);
    expect(literalStringErrors(seed("packages/ui/src/x.tsx", "const a = <p>Hello there</p>;"))).not.toEqual([]);
    expect(literalStringErrors(seed("packages/ui/src/x.tsx", 'const a = <input placeholder="Type here" />;'))).not.toEqual([]);
    expect(keyErrors(seed("packages/ui/src/x.tsx", 't("no.such.key")'), BASE).some((e) => e.startsWith("missing"))).toBe(true);
  });
});

describe("LOC-01", () => {
  test("loc01_no_literal_strings", () => expect(literalStringErrors(files)).toEqual([]));

  test("loc01_keys_resolve", () => {
    expect(keyErrors([...files, ...sources(["packages/client-core/src"])], BASE)).toEqual([]);
  });

  test("client helpers may return translated text keys while unrelated keys remain checked", () => {
    const keys = { "help.ask.hint": "Hint", "help.ask.walk_through": "Walk through" };
    expect(keyErrors(seed("packages/client-core/src/chips.ts", 'return { textKey: `help.ask.${kind}` };'), keys)).toEqual([]);
    expect(keyErrors(seed("packages/client-core/src/chips.ts", 'return { debug: `help.ask.${kind}` };'), keys)).toHaveLength(2);
  });
});

describe("DSN-14", () => {
  test("dsn14_contracts_have_tests", () => {
    const design = fs.readFileSync(path.join(ROOT, "apps/desktop/DESIGN.md"), "utf8");
    const named = [...design.matchAll(/test: `([a-z0-9_]+)`/g)].map((m) => m[1]!);
    expect(named.length).toBeGreaterThanOrEqual(5);
    const testText = sources(["packages", "apps/desktop"], [".ts", ".tsx"]).map((f) => f.text).join("\n");
    for (const name of named) expect(testText, name).toMatch(new RegExp(`["'\`]${name}["'\`]`));
  });
});


test("catalogue use includes template keys inside conditional translation arguments", () => {
  const keys = { "board.status.draft": "Draft", "board.status.checking_student": "Checking" };
  const code = 't(step.status === "checking" && owner === "student" ? "board.status.checking_student" : `board.status.${step.status}`)';
  expect(keyErrors(seed("packages/ui/src/x.tsx", code), keys)).toEqual([]);
  expect(keyErrors(seed("packages/ui/src/x.tsx", code), { ...keys, "really.unused": "Unused" })).toEqual(["unused key really.unused"]);
});
