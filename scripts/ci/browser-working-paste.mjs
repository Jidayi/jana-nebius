// Synthetic clipboard event tests the shipping browser handler; native Ctrl+Enter submits.
// OS clipboard integration and native assistive technology remain separate qualification.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const lines = JSON.parse(await readFile("packages/ui/gallery/working-paste-golden.json", "utf8"));
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${server.url}/gallery.html?benchmark=input-flows&theme=${theme}`);
    const editor = page.locator(".tiptap"); await editor.waitFor();
    for (let i = 0; i < 50 && !await editor.evaluate((el) => el === globalThis.document.activeElement); i++) await page.keyboard.press("Tab");
    if (!await editor.evaluate((el) => el === globalThis.document.activeElement)) throw new Error("Editor unreachable");
    await editor.evaluate((el, text) => {
      const transfer = new globalThis.DataTransfer(); transfer.setData("text/plain", text);
      el.dispatchEvent(new globalThis.ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true }));
    }, lines.join("\r\n"));
    await page.waitForFunction(() => globalThis.__jana_input_evidence.text.includes("s = 30/3"));
    const numbers = await page.locator("[data-line-numbers] > div").allTextContents();
    if (JSON.stringify(numbers) !== JSON.stringify(lines.map((_, i) => String(i + 1)))) throw new Error(`Wrong line numbers: ${numbers}`);
    await page.keyboard.press("Control+Enter"); await page.waitForFunction(() => globalThis.__jana_input_evidence.sent.length === 1);
    const evidence = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (evidence.sent[0].text !== lines.join("\n") || !evidence.sent[0].pasted || JSON.stringify(evidence.sent[0].blocks) !== JSON.stringify([{ type: "text", text: lines.join("\n") }])) throw new Error(`Wrong ordered working: ${JSON.stringify(evidence)}`);
    const audit = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => v.id)));
    results.push({ theme, numbers, evidence, paste_event_synthetic: true, keyboard_submit_native: true, violations: 0 }); await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== 2 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
