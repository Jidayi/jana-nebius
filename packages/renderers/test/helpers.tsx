// Test helpers for the renderer suites: the engine-resolved fixtures (scripts/jana_tools/visual_fixtures.py), a
// renderer by kind, static drawing in a label mode at a step, theme resolution of token colours for golden renders,
// and a line diff a reviewer can read.
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { translator } from "../../i18n/src/index.js";
import { RENDERERS, type LabelMode, type ResolvedSpec, type VisualRenderer } from "../src/index.js";
import { THEME } from "../src/generated/theme.js";

export const ROOT = path.resolve(import.meta.dirname, "../../..");
export const FIXTURES = path.resolve(import.meta.dirname, "../fixtures");
export const GOLDEN = path.resolve(import.meta.dirname, "../golden");
export const t = translator("en");

export interface Fixture {
  id: string;
  kind: string;
  subject: string;
  modes: LabelMode[];
  spec: ResolvedSpec;
  claims: string[];
}

export function fixtures(): Fixture[] {
  const dir = path.join(FIXTURES, "visuals");
  return fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) as Fixture);
}

export function catalogue(): { kind: string; renderer: string; stage: string; group: string; channel: string; subjects: string[]; priority: string }[] {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, "catalogue.json"), "utf8")).kinds;
}

export function rendererOf(kind: string): VisualRenderer {
  const r = RENDERERS.find((x) => x.kind === kind);
  if (r === undefined) throw new Error(`no renderer for ${kind}`);
  return r;
}

export function stepsOf(spec: ResolvedSpec): number {
  return ((spec.steps as unknown[] | undefined) ?? []).length;
}

export interface DrawOptions {
  step?: number;
  labels?: LabelMode;
  focus?: string[];
  textScale?: number;
  reducedMotion?: boolean;
}

export function draw(spec: ResolvedSpec, o: DrawOptions = {}): string {
  const R = rendererOf(spec.type);
  return renderToStaticMarkup(
    <R.Component spec={spec} step={o.step ?? Math.max(0, stepsOf(spec) - 1)} labels={o.labels ?? "shown"} focus={o.focus ?? []} size={{ width: 480, height: 320 }}
      reducedMotion={o.reducedMotion ?? true} onPartActivate={() => undefined} t={t} textScale={o.textScale ?? 1} />,
  );
}

export function dom(markup: string): HTMLElement {
  const doc = new DOMParser().parseFromString(`<!doctype html><html><body><div id="root">${markup}</div></body></html>`, "text/html");
  return doc.getElementById("root") as HTMLElement;
}

const FOCUSABLE = "input, select, button, textarea, [tabindex]";

/** The [data-part] elements a keyboard reaches, in document order. */
export function focusableParts(root: HTMLElement): string[] {
  return [...root.querySelectorAll<HTMLElement>("[data-part]")]
    .filter((el) => el.matches(FOCUSABLE) && el.getAttribute("tabindex") !== "-1")
    .map((el) => el.getAttribute("data-part") ?? "");
}

/** Token colours resolved for a theme (golden renders, DSN-18): aliases first, then the theme's value. */
export function resolveTheme(markup: string, theme: "light" | "dark"): { text: string; unresolved: string[] } {
  const colours = THEME.color as unknown as Record<string, { light: string; dark: string }>;
  const aliases = THEME.aliases as unknown as Record<string, string>;
  const swatches = Object.fromEntries(Object.entries(THEME.content).map(([k, v]) => [k, { value: v }])) as Record<string, { value: string }>;
  const unresolved: string[] = [];
  const text = markup.replace(/var\(--(color|content)-([a-z0-9-]+)\)/g, (whole, family: string, name: string) => {
    if (family === "content") {
      const swatch = swatches[name];
      if (swatch === undefined) unresolved.push(whole);
      return swatch?.value ?? whole;
    }
    const token = colours[aliases[name] ?? name];
    if (token === undefined) {
      unresolved.push(whole);
      return whole;
    }
    return token[theme];
  });
  return { text, unresolved };
}

/** One element per line, so a golden difference reads as the elements that changed. */
export function pretty(markup: string): string {
  return markup.replace(/></g, ">\n<").trim() + "\n";
}

export function lineDiff(before: string, after: string): string[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const out: string[] = [];
  const n = Math.max(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    if (a[i] !== b[i]) {
      if (a[i] !== undefined) out.push(`- ${a[i]}`);
      if (b[i] !== undefined) out.push(`+ ${b[i]}`);
    }
  }
  return out;
}

export function variants(spec: ResolvedSpec): Record<string, string> {
  const light = resolveTheme(pretty(draw(spec)), "light").text;
  const dark = resolveTheme(pretty(draw(spec)), "dark").text;
  const large = resolveTheme(pretty(draw(spec, { textScale: 1.5 })), "light").text;
  return { light, dark, large };
}

export function readGolden(id: string, variant: string): string | null {
  const file = path.join(GOLDEN, `${id}.${variant}.html`);
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
}

export function writeGolden(id: string, variant: string, text: string): void {
  fs.mkdirSync(GOLDEN, { recursive: true });
  fs.writeFileSync(path.join(GOLDEN, `${id}.${variant}.html`), text);
}

/** The visible text of an element tree, label by label. */
export function texts(root: HTMLElement): string[] {
  return [...root.querySelectorAll("text, td, th, span, p, dd, output, caption")].map((el) => (el.textContent ?? "").trim()).filter(Boolean);
}
