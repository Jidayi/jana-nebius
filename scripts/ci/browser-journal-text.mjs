import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const golden = JSON.parse(await readFile("packages/ui/gallery/journal-text-golden.json", "utf8"));
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
    const tabTo = async (target) => { for (let i = 0; i < 100; i++) { if (await target.evaluate((el) => el === globalThis.document.activeElement)) return; await page.keyboard.press("Tab"); } throw new Error("Unreachable control"); };
    await tabTo(page.locator(".tiptap")); await page.keyboard.insertText(golden.source);
    const convert = page.getByRole("button", { name: "Make this a journal?", exact: true }); await convert.waitFor();
    const before = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (before.text !== golden.source || before.blocks.some((b) => b.type === "ledger_table") || before.sent.length) throw new Error("Recognition altered/submitted the draft");
    await tabTo(convert); await page.keyboard.press("Enter");
    const table = page.getByRole("table", { name: "Journal", exact: true }); await table.waitFor();
    const converted = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (converted.sent.length || JSON.stringify(converted.blocks) !== JSON.stringify([golden.block])) throw new Error(`Wrong requested conversion: ${JSON.stringify(converted)}`);
    await tabTo(table.getByRole("textbox").first()); await page.keyboard.press("Control+Enter");
    await page.waitForFunction(() => globalThis.__jana_input_evidence.sent.length === 1);
    const evidence = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (JSON.stringify(evidence.sent[0].blocks) !== JSON.stringify([golden.block]) || evidence.sent[0].pasted || pointerEvents) throw new Error("Wrong serialized conversion");
    const audit = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => v.id)));
    results.push({ theme, pointer_events: pointerEvents, before, evidence, violations: 0 }); await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== 2 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
