import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) for (const width of [800, 1366]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); await page.setViewportSize({ width, height: 900 }); page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${server.url}/gallery.html?state=photo-capture.canonical.drafting&theme=${theme}`);
    const targets = [];
    for (let index = 0; index < 4; index++) {
      const corner = page.getByRole("button", { name: `Crop corner ${index + 1}`, exact: true }); await corner.waitFor();
      for (let n = 0; n < 60 && !await corner.evaluate((el) => el === globalThis.document.activeElement); n++) await page.keyboard.press("Tab");
      if (!await corner.evaluate((el) => el === globalThis.document.activeElement)) throw new Error(`Corner ${index + 1} is not reachable by Tab`);
      const x = [0, 1, 1, 0][index], y = [0, 0, 1, 1][index];
      const check = async (expectedX, expectedY) => {
        await page.waitForFunction(({ label, x, y }) => {
          const button = globalThis.document.querySelector(`button[aria-label="${label}"]`); if (!button) return false;
          const rect = button.getBoundingClientRect(), parent = button.parentElement.getBoundingClientRect();
          return Math.abs((rect.left + rect.width / 2 - parent.left) / parent.width - x) < .0001 && Math.abs((rect.top + rect.height / 2 - parent.top) / parent.height - y) < .0001;
        }, { label: `Crop corner ${index + 1}`, x: expectedX, y: expectedY });
      };
      await check(x, y);
      await page.keyboard.press(x === 0 ? "ArrowRight" : "ArrowLeft"); await check(x === 0 ? .01 : .99, y);
      await page.keyboard.press(y === 0 ? "Shift+ArrowDown" : "Shift+ArrowUp"); await check(x === 0 ? .01 : .99, y === 0 ? .05 : .95);
      const description = await corner.getAttribute("aria-description");
      if (!description?.includes(`${x === 0 ? 1 : 99}% from the left; ${y === 0 ? 5 : 95}% from the top`)) throw new Error("Accessible position did not follow the crop handle");
      for (let n = 0; n < 2; n++) { await page.keyboard.press(x === 0 ? "Shift+ArrowLeft" : "Shift+ArrowRight"); await page.keyboard.press(y === 0 ? "Shift+ArrowUp" : "Shift+ArrowDown"); }
      await check(x, y); targets.push({ corner: index + 1, description, clamped: true });
    }
    const audit = await new AxeBuilder({ page }).include("[data-gallery-id]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => v.id)));
    results.push({ theme, width, targets, violations: 0, keyboard_only: true }); await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== 4 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
