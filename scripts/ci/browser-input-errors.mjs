import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${server.url}/gallery.html?state=math-input.canonical&theme=${theme}`);
    for (const [source, position] of [["x=(2", 4], ["x=□", 2], ["sinx", 0], ["x=2=3", 3], ["x".repeat(2001), 2000], ["25 C", 3]]) {
      await page.locator("[data-math-node] button").click();
      const input = page.getByRole("textbox", { name: "Maths as typed", exact: true }); await input.fill(source);
      const marker = page.locator("[data-input-error-position]"); await marker.waitFor();
      if (await marker.getAttribute("data-input-error-position") !== String(position)) throw new Error("Incorrect error position");
      const dotted = await marker.evaluate((el) => globalThis.getComputedStyle(el).textDecorationStyle);
      if (dotted !== "dotted") throw new Error("Error position has no dotted underline");
      await page.getByRole("button", { name: "Maths keyboard", exact: true }).click();
      if (!await input.isVisible() || await input.inputValue() !== source) throw new Error("Blurring discarded an invalid draft");
      await page.getByRole("button", { name: "Maths keyboard", exact: true }).click();
      const audit = await new AxeBuilder({ page }).include("[data-gallery-id]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))));
      results.push({ theme, source: source.length > 40 ? "over length limit" : source, position, dotted, violations: 0 });
      await input.press("Escape"); // restore the preceding committed value for the next case
    }
    await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== 12 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
