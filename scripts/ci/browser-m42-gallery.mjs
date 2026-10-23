// Reproducible M42 compact/large-text WCAG and layout corpus. Synthetic; does not replace native AT.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
import { layoutAudit } from "./layout-audit.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const root = "packages/ui/gallery/states";
const states = await Promise.all((await readdir(root)).filter((f) => f.startsWith("study-workspace.")).map(async (f) => JSON.parse(await readFile(path.join(root, f), "utf8"))));
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
context.setDefaultTimeout(5000);
try {
 for (const theme of ["light", "dark"]) for (const width of [320, 800, 1366]) for (const scale of [1, 2]) for (const state of states) {
  const page = await context.newPage(); await page.setViewportSize({ width, height: 900 }); page.on("pageerror", (e) => errors.push(e.message));
  try {
   await page.goto(`${server.url}/gallery.html?state=${state.id}&theme=${theme}&scale=${scale}`);
   for (const text of state.expectText) await page.locator("[data-gallery-id]").getByText(text, { exact: false }).first().waitFor();
   const audit = await new AxeBuilder({ page }).include("[data-gallery-id]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
   const layout = await page.locator("[data-gallery-id]").evaluate(layoutAudit);
   const failed = audit.violations.length > 0 || layout.horizontal_overflow || !layout.scale_applied || layout.clipped.length > 0 || layout.overlaps.length > 0;
   results.push({ state: state.id, theme, width, scale, passed: !failed, violations: audit.violations.map((v) => v.id), layout });
   if (failed) await page.screenshot({ path: path.join(out, `${state.id}-${theme}-${width}-${scale}.png`), fullPage: true });
  } catch (error) { errors.push(`${state.id}/${theme}/${width}/${scale}: ${error.stack ?? error.message}`); }
  console.log(`M42 gallery ${results.length + errors.length}/${states.length * 12}: ${state.id}/${width}/${scale}`);
  await page.close();
 }
} finally { await browser.close(); await server.close(); }
const expected = states.length * 12;
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, expected, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== expected || errors.length || results.some((r) => !r.passed)) { console.error(`${results.filter((r) => !r.passed).length} layout/a11y failures; ${errors.length} errors`); process.exitCode = 1; }
