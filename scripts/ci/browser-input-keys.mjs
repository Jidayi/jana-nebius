// Native Tab/arrow traversal of every palette control; no pointer or assistive-technology qualification.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2] ?? "dist/input-keys"); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) {
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${server.url}/gallery.html?state=math-input.canonical&theme=${theme}`);
    const tabTo = async (target) => { await target.waitFor(); for (let i = 0; i < 100; i++) { if (await target.evaluate((el) => el === globalThis.document.activeElement)) return; await page.keyboard.press("Tab"); } throw new Error("Palette control not reachable by Tab"); };
    const toggle = page.getByRole("button", { name: "Maths keyboard", exact: true }); await tabTo(toggle); await page.keyboard.press("Enter");
    const tabs = page.getByRole("tab"); await tabTo(page.getByRole("tab", { name: "Basic", exact: true }));
    for (let index = 0; index < 5; index++) {
      const currentTab = tabs.nth(index); if (index) await page.keyboard.press("ArrowRight");
      if (await currentTab.getAttribute("aria-selected") !== "true") throw new Error("Tab arrow did not select its palette");
      await page.keyboard.press("Tab");
      const toolbar = page.getByRole("toolbar"), keys = toolbar.getByRole("button"), count = await keys.count(), names = [];
      for (let i = 0; i < count; i++) {
        const key = keys.nth(i); if (!(await key.evaluate((el) => el === globalThis.document.activeElement))) throw new Error(`Arrow did not reach key ${i}`);
        const name = (await key.getAttribute("aria-label")) ?? await key.textContent(); if (!name?.trim()) throw new Error("Unnamed palette key"); names.push(name);
        await page.keyboard.press("ArrowRight");
      }
      if (!(await keys.first().evaluate((el) => el === globalThis.document.activeElement))) throw new Error("Key traversal did not wrap");
      await page.keyboard.press("End"); if (!(await keys.last().evaluate((el) => el === globalThis.document.activeElement))) throw new Error("End did not reach last key");
      await page.keyboard.press("Home"); if (!(await keys.first().evaluate((el) => el === globalThis.document.activeElement))) throw new Error("Home did not reach first key");
      const audit = await new AxeBuilder({ page }).include('[data-gallery-id]').withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))));
      results.push({ theme, tab: await currentTab.textContent(), count, names });
      await page.keyboard.press("Shift+Tab"); // one toolbar Tab stop returns to the active palette tab
      if (!(await currentTab.evaluate((el) => el === globalThis.document.activeElement))) throw new Error("Toolbar did not return to its active tab");
    }
    await page.close();
  }
} catch (error) { errors.push(error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ test: "loc21_maths_input_parity", synthetic: true, native_screen_reader: false, results, errors }, null, 2));
if (results.length !== 10 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
