import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) for (const mime of ["text/plain", "text/html"]) for (const action of ["choose", "cancel", "cancel_button"]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${server.url}/gallery.html?benchmark=input-flows&flow=question&theme=${theme}`);
    const editor = page.locator(".tiptap"); await editor.waitFor();
    const tabTo = async (target) => { for (let i = 0; i < 100; i++) { if (await target.evaluate((el) => el === globalThis.document.activeElement)) return; await page.keyboard.press("Tab"); } throw new Error("Unreachable control"); };
    await tabTo(editor); await page.keyboard.insertText("Prior typed draft");
    await editor.evaluate((el, mime) => {
      const data = new globalThis.DataTransfer(); data.setData(mime, mime === "text/plain" ? Array.from({ length: 5 }, (_, i) => `${i + 1}. Find value ${i + 1}?`).join("\n") : `<ol>${Array.from({ length: 5 }, (_, i) => `<li>Find value ${i + 1}?</li>`).join("")}</ol>`);
      el.dispatchEvent(new globalThis.ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
    }, mime);
    const picker = page.getByRole("group", { name: "Choose one question to work on first.", exact: true }); await picker.waitFor();
    if (await picker.getByRole("button").count() !== 6) throw new Error("Wrong picker inventory");
    await page.keyboard.press("Control+Enter");
    const before = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (before.text !== "Prior typed draft" || before.sent.length) throw new Error("Picker altered/submitted the draft");
    const audit = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => v.id)));
    if (action === "choose") { await tabTo(picker.getByRole("button", { name: "Question 3: Find value 3?", exact: true })); await page.keyboard.press("Enter"); }
    else if (action === "cancel") { await tabTo(picker.getByRole("button", { name: "Question 1: Find value 1?", exact: true })); await page.keyboard.press("Escape"); }
    else { await tabTo(picker.getByRole("button", { name: "Cancel", exact: true })); await page.keyboard.press("Enter"); }
    await picker.waitFor({ state: "detached" });
    await page.waitForFunction(() => globalThis.document.activeElement?.matches(".tiptap"));
    if (await page.evaluate(() => globalThis.__jana_input_evidence.sent.length)) throw new Error("Choice/cancellation sent a turn");
    await page.keyboard.press("Control+Enter"); await page.waitForFunction(() => globalThis.__jana_input_evidence.sent.length === 1);
    const evidence = await page.evaluate(() => globalThis.__jana_input_evidence), expected = action === "choose" ? "Find value 3?" : "Prior typed draft";
    if (evidence.sent[0].text !== expected || evidence.sent[0].pasted !== (action === "choose")) throw new Error(`Wrong chosen/original draft: ${JSON.stringify(evidence)}`);
    results.push({ theme, mime, action, before, evidence, violations: 0, clipboard_event_synthetic: true }); await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, os_clipboard_qualified: false }, null, 2));
if (results.length !== 12 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
