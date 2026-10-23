import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const golden = JSON.parse(await readFile("packages/ui/gallery/journal-entry-golden.json", "utf8"));
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${server.url}/gallery.html?benchmark=input-flows&theme=${theme}`);
    await page.locator("main .tiptap").waitFor();
    let pointerEvents = 0; await page.exposeFunction("recordPointer", () => pointerEvents++);
    await page.evaluate(() => globalThis.document.addEventListener("pointerdown", () => globalThis.recordPointer()));
    const tabTo = async (target) => {
      for (let i = 0; i < 100; i++) { if (await target.evaluate((el) => el === globalThis.document.activeElement)) return; await page.keyboard.press("Tab"); }
      throw new Error("Unreachable control");
    };
    await tabTo(page.locator(".tiptap")); await page.keyboard.press("Alt+m");
    await page.waitForFunction(() => globalThis.document.activeElement?.matches('[role="tab"][aria-selected="true"]'));
    if (await page.getByRole("tab", { name: "Accounting" }).getAttribute("aria-selected") !== "true") throw new Error("Wrong subject default");
    await page.keyboard.press("Tab"); await page.keyboard.press("Home"); for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter"); const table = page.getByRole("table", { name: "Journal", exact: true }); await table.waitFor();
    await tabTo(table.getByRole("textbox").first());
    for (let row = 0; row < golden.rows.length; row++) {
      for (let col = 0; col < golden.rows[row].length; col++) {
        const expected = table.locator(`input[data-cell="${row * 5 + col}"]`); await expected.waitFor();
        if (!await expected.evaluate((el) => el === globalThis.document.activeElement)) throw new Error(`Wrong cell order ${row}/${col}`);
        if (golden.rows[row][col]) await page.keyboard.insertText(golden.rows[row][col]);
        if (!(row === 2 && col === 4)) await page.keyboard.press("Tab");
      }
    }
    const money = await table.locator('[data-cell="3"]').evaluate((el) => globalThis.getComputedStyle(el).textAlign);
    if (!["end", "right"].includes(money)) throw new Error("Amount not right-aligned");
    await page.keyboard.press("Control+Enter");
    await page.waitForFunction(() => globalThis.__jana_input_evidence.sent.length === 1);
    const evidence = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (JSON.stringify(evidence.sent[0].blocks) !== JSON.stringify([golden.block])) throw new Error(`Wrong wire document ${JSON.stringify(evidence)}`);
    if (evidence.sent[0].text !== golden.block.text_fallback || evidence.sent[0].pasted || pointerEvents) throw new Error("Wrong fallback/input origin");
    const audit = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) }))));
    results.push({ theme, background: await page.locator("main").evaluate((el) => globalThis.getComputedStyle(el).backgroundColor), pointer_events: pointerEvents, money_align: money, evidence, violations: 0 }); await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
if (results.length === 2 && results[0].background === results[1].background) errors.push("Themes did not change the surface");
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== 2 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
