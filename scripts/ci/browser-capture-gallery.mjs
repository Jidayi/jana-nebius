import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const root = "packages/ui/gallery/states";
const states = await Promise.all((await readdir(root)).filter((f) => f.startsWith("photo-capture.")).map(async (f) => JSON.parse(await readFile(path.join(root, f), "utf8"))));
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
 for (const theme of ["light", "dark"]) for (const width of [800, 1366]) for (const state of states) {
  const page = await context.newPage(); await page.setViewportSize({ width, height: 900 }); page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${server.url}/gallery.html?state=${state.id}&theme=${theme}`);
  for (const text of state.expectText) await page.getByText(text, { exact: false }).first().waitFor();
  if (state.variant === "corner-focused" && await page.locator(":focus").getAttribute("aria-label") !== "Crop corner 1") throw new Error("Corner focus missing");
  const audit = await new AxeBuilder({ page }).include("[data-gallery-id]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  if (audit.violations.length) throw new Error(`${state.id}: ${JSON.stringify(audit.violations.map((v) => v.id))}`);
  results.push({ state: state.id, theme, width, violations: 0 }); await page.close();
 }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, expected: states.length * 4, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== states.length * 4 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
