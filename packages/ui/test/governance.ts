// Design governance checks (DSN-13): plain functions over source text, run on every commit against the real files and,
// for `dsn13_governance_seeded_violations`, against a seeded violation of each rule.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { TOKENS } from "../src/generated/tokens.js";

export interface Source {
  path: string;
  text: string;
}

const ROOT = path.resolve(import.meta.dirname, "../../..");
export const COMPONENT_DIRS = ["packages/ui/src", "packages/renderers/src", "apps/desktop/src"];

export function sources(dirs = COMPONENT_DIRS, exts = [".ts", ".tsx", ".css"]): Source[] {
  const out: Source[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== "generated" && entry.name !== "node_modules") walk(full);
      } else if (exts.some((e) => entry.name.endsWith(e))) {
        out.push({ path: path.relative(ROOT, full), text: fs.readFileSync(full, "utf8") });
      }
    }
  };
  for (const dir of dirs) walk(path.join(ROOT, dir));
  return out;
}

const HEX = /(?<![\w&])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])/;

/** test_dsn13_no_raw_hex and dsn01_no_seed_in_components: colours come only from role tokens. */
export function rawColourErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    f.text.split("\n").forEach((line, i) => {
      const code = line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "");
      if (HEX.test(code)) errors.push(`${f.path}:${i + 1}: raw hex colour`);
      if (/\brgba?\(|\bhsla?\(/.test(code)) errors.push(`${f.path}:${i + 1}: raw colour function`);
      if (/\bseeds\b|--seed-/.test(code)) errors.push(`${f.path}:${i + 1}: seed token referenced`);
    });
  }
  return errors;
}

const RADII = ["control", "chip", "card", "composer", "dialog", "sheet", "pill", "none", "full"];
const SHADOWS = ["overlay-1", "overlay-2", "dock", "none"];  // dock: the floating composer only (DSN-08, D89)

function classTokens(text: string): string[] {
  return [...text.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)].flatMap((m) => (m[1] ?? m[2] ?? "").split(/\s+/));
}

/** dsn08_radius_from_tokens: radius, shadow and spacing only from tokens. */
export function radiusErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    for (const cls of classTokens(f.text)) {
      const radius = /^(?:[a-z]+:)*rounded(?:-[a-z]{1,2})?-(.+)$/.exec(cls);
      if (radius && !RADII.includes(radius[1] ?? "")) errors.push(`${f.path}: radius class ${cls}`);
      const shadow = /^(?:[a-z]+:)*shadow-(.+)$/.exec(cls);
      if (shadow && !SHADOWS.includes(shadow[1] ?? "")) errors.push(`${f.path}: shadow class ${cls}`);
      if (/^(?:[a-z]+:)*-?[mp][trblxyse]?-\[/.test(cls) || /^(?:[a-z]+:)*gap-\[/.test(cls)) errors.push(`${f.path}: arbitrary spacing ${cls}`);
    }
    if (f.path.endsWith(".css") && !f.path.includes("generated") && /border-radius:\s*(?!var\(--radius)/.test(f.text)) errors.push(`${f.path}: raw border-radius`);
  }
  return errors;
}

/** dsn08_radius_from_tokens (D89): the `dock` shadow and the `composer` radius belong to the floating composer and
 * nothing else, so they appear only in its shell primitive. */
export function dockErrors(files: Source[]): string[] {
  return files
    .filter((f) => !f.path.endsWith("primitives/ComposerShell.tsx") && /\b(?:shadow-dock|rounded(?:-[a-z]{1,2})?-composer)\b|--shadow-dock|--radius-composer/.test(f.text))
    .map((f) => `${f.path}: the composer's dock shadow or radius outside the composer shell`);
}

/** The stacking levels of the token contract's `zIndex` group (`z-popover`, `z-dialog`…), the only ones there are. */
const Z_LEVELS: string[] = Object.keys(TOKENS.zIndex);

/** Every whitespace-separated word inside a string or template literal: class lists built in variables and
 * ternaries as well as the ones written straight into `className`. */
function literalWords(text: string): string[] {
  return [...text.matchAll(/"([^"\n]*)"|`([^`]*)`|'([^'\n]*)'/g)].flatMap((m) => (m[1] ?? m[2] ?? m[3] ?? "").split(/\s+/));
}

function stackingWord(file: string, word: string, errors: string[]): void {
  const level = /^!?(?:[^\s:]+:)*!?-?z-(.+?)!?$/.exec(word);
  if (level && !Z_LEVELS.includes(level[1] ?? "")) errors.push(`${file}: stacking class ${word}`);
}

/** dsn08_radius_from_tokens (elevation): stacking order only from the `zIndex` tokens: no `z-50`, `z-[…]` or `z-(…)`
 * utilities, no inline `zIndex`, and `z-index` in stylesheets only through `var(--z-…)`. */
export function zIndexErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    if (f.path.endsWith(".css")) {
      for (const m of f.text.matchAll(/z-index:\s*([^;}]+)/g)) {
        const value = (m[1] ?? "").trim();
        if (!/^var\(--z-[a-z]+\)$/.test(value)) errors.push(`${f.path}: raw z-index ${value}`);
      }
      for (const m of f.text.matchAll(/@apply[^;]*/g)) for (const word of m[0].split(/\s+/)) stackingWord(f.path, word, errors);
      continue;
    }
    for (const word of new Set([...classTokens(f.text), ...literalWords(f.text)])) stackingWord(f.path, word, errors);
    if (/\bzIndex\s*:/.test(f.text)) errors.push(`${f.path}: inline zIndex`);
  }
  return errors;
}

/** dsn07_named_sizes_only: font sizes only from the named sizes (seven since D89, display included; maths sizes come
 * from the math tokens). */
export function sizeErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    for (const cls of classTokens(f.text)) {
      const size = /^(?:[a-z]+:)*text-(xs|sm|base|lg|xl|[2-9]xl|\[.+\])$/.exec(cls);
      if (size) errors.push(`${f.path}: font size ${cls}`);
    }
    if (/fontSize[=:]\s*\{?\s*["'`]?\d/.test(f.text) && !f.path.includes("renderers")) errors.push(`${f.path}: inline font size`);
    if (f.path.endsWith(".css") && /font-size:(?!\s*var\(--(text|math)-)/.test(f.text)) errors.push(`${f.path}: raw font-size`);
  }
  return errors;
}

/** test_dsn13_no_numeric_weight_or_caps: named weights only, no all-caps styling. */
export function weightCapsErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    for (const cls of classTokens(f.text)) {
      if (/^(?:[a-z]+:)*font-(bold|extrabold|black|light|thin|\[\d+\])$/.test(cls)) errors.push(`${f.path}: weight ${cls}`);
      if (/^(?:[a-z]+:)*uppercase$/.test(cls)) errors.push(`${f.path}: uppercase`);
    }
    if (/font-weight:\s*\d/.test(f.text) || /text-transform:\s*uppercase/.test(f.text)) errors.push(`${f.path}: raw weight or caps`);
  }
  return errors;
}

/** The motion primitive files (TABLE DSN-10a): the shared primitives, and the tutor presence's own (DSN-27). */
const MOTION_PRIMITIVES = ["primitives/motion.css", "tutor/presence.css"];

/** dsn09_motion_contract and dsn10_primitives_only: motion lives in the primitive files, with reduced-motion rules. */
export function motionErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    const primitive = MOTION_PRIMITIVES.some((p) => f.path.endsWith(p));
    if (/@keyframes/.test(f.text) && !primitive) errors.push(`${f.path}: keyframes outside the motion primitives`);
    if (/transition:\s*all|transition-all\b/.test(f.text)) errors.push(`${f.path}: transition all`);
    if (/(^|[\s"`])(?:[a-z]+:)*(animate-[a-z]|transition(?:-[a-z]+)?|duration-\d)/m.test(classTokens(f.text).join(" "))) errors.push(`${f.path}: motion utility outside the primitives`);
    if (primitive && /@keyframes|transition:/.test(f.text) && !/prefers-reduced-motion/.test(f.text)) errors.push(`${f.path}: no reduced-motion block`);
    if (/jana-spinner|LoaderCircle/.test(f.text) && !/primitives\/|icons\.tsx$/.test(f.path)) errors.push(`${f.path}: spinner outside the primitives`);
  }
  return errors;
}

/** dsn11_icon_map_unique: one pack, imported only through the name map, one glyph per concept. */
export function iconErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    if (/from\s+["'](lucide-react|lucide|@heroicons|react-icons|@phosphor-icons)/.test(f.text) && !f.path.endsWith("src/icons.tsx")) errors.push(`${f.path}: icon pack imported outside the name map`);
    if (f.path.endsWith("src/icons.tsx")) {
      const glyphs = [...f.text.matchAll(/glyph:\s*([A-Za-z]+)/g)].map((m) => m[1]);
      const dupes = glyphs.filter((g, i) => glyphs.indexOf(g) !== i);
      for (const d of new Set(dupes)) errors.push(`${f.path}: glyph ${d} serves two concepts`);
    }
  }
  return errors;
}

/** dsn12_primitive_monopoly: no home-made loaders, empties, errors or confirms; no native title tooltips. */
export function monopolyErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    if (!f.path.endsWith(".tsx")) continue;
    if (/\stitle=\{|\stitle="/.test(f.text) && !/<svg|<title/.test(f.text)) errors.push(`${f.path}: native title tooltip`);
    if (f.path.includes("primitives/")) continue;
    if (/role="alertdialog"|window\.confirm\(/.test(f.text)) errors.push(`${f.path}: confirm pattern outside ConfirmDialog`);
    if (/role="alert"/.test(f.text)) errors.push(`${f.path}: error pattern outside ErrorState`);
  }
  return errors;
}

/** dsn02_no_danger_in_learning: `danger` is for system failures, never board, practice or feedback components. */
export function dangerErrors(files: Source[]): string[] {
  return files.filter((f) => /\/(board|transcript|practice|feedback)\//.test(f.path) && /\bdanger\b/.test(f.text)).map((f) => `${f.path}: danger in a learning component`);
}

const USER_ATTRIBUTES = new Set(["aria-label", "placeholder", "alt", "title", "aria-description", "label"]);

/** loc01_no_literal_strings: no user-visible literal in JSX text or user-facing attributes. */
export function literalStringErrors(files: Source[]): string[] {
  const errors: string[] = [];
  for (const f of files) {
    if (!f.path.endsWith(".tsx")) continue;
    const sf = ts.createSourceFile(f.path, f.text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const visit = (node: ts.Node) => {
      if (ts.isJsxText(node) && /[A-Za-z]{2,}/.test(node.text)) {
        errors.push(`${f.path}:${sf.getLineAndCharacterOfPosition(node.pos).line + 1}: literal text "${node.text.trim().slice(0, 30)}"`);
      }
      if (ts.isJsxAttribute(node) && USER_ATTRIBUTES.has(node.name.getText(sf)) && node.initializer !== undefined && ts.isStringLiteral(node.initializer) && /[A-Za-z]{2,}/.test(node.initializer.text)) {
        errors.push(`${f.path}:${sf.getLineAndCharacterOfPosition(node.pos).line + 1}: literal attribute ${node.name.getText(sf)}`);
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return errors;
}

/** loc01_keys_resolve: every key used exists in the base catalogue, and no base key is unused. */
export function keyErrors(files: Source[], base: Record<string, string>): string[] {
  const errors: string[] = [];
  const literals = new Set<string>();
  const prefixes = new Set<string>();
  for (const f of files) {
    for (const m of f.text.matchAll(/\bt\(\s*"([a-z0-9_.]+)"/g)) literals.add(m[1] ?? "");
    const source = ts.createSourceFile(f.path, f.text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const argument = (node: ts.Node) => {
      if (ts.isStringLiteral(node) && /^[a-z0-9_.]+$/.test(node.text)) literals.add(node.text);
      if (ts.isTemplateExpression(node) && /^[a-z0-9_.]*$/.test(node.head.text)) prefixes.add(node.head.text);
      if (ts.isConditionalExpression(node)) { argument(node.whenTrue); argument(node.whenFalse); }
      if (ts.isParenthesizedExpression(node)) argument(node.expression);
    };
    const visit = (node: ts.Node) => {
      if (ts.isCallExpression(node) && node.arguments[0] && ((ts.isIdentifier(node.expression) && node.expression.text === "t") || (ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "t"))) argument(node.arguments[0]);
      ts.forEachChild(node, visit);
    };
    visit(source);
    for (const m of f.text.matchAll(/["']([a-z]+(?:\.[a-z0-9_]+)+)["']/g)) if ((m[1] ?? "") in base) literals.add(m[1] ?? "");
  }
  for (const key of literals) if (!(key in base)) errors.push(`missing key ${key}`);
  for (const key of Object.keys(base)) {
    if (!literals.has(key) && ![...prefixes].some((p) => p !== "" && key.startsWith(p))) errors.push(`unused key ${key}`);
  }
  return errors;
}
