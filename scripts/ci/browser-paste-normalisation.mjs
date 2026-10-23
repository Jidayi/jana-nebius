// Synthetic clipboard MIME fixtures exercise the real browser parser; OS clipboard qualification is separate.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const fixtures = JSON.parse(await readFile("packages/ui/gallery/paste-golden.json", "utf8"));
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const results = [], errors = [], egress = []; let mutationDetected = false;
await context.route("**/*", (route) => new URL(route.request().url()).origin === new URL(server.url).origin ? route.continue() : route.abort());

try {
  for (const theme of ["light", "dark"]) for (const source of ["paste", "drop"]) for (const fixture of fixtures) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (request) => {
      if (new URL(request.url()).origin === new URL(server.url).origin) return;
      if (request.url().endsWith("/paste-mutation-control")) mutationDetected = true; else egress.push(request.url());
    });
    await page.goto(`${server.url}/gallery.html?benchmark=input-flows&theme=${theme}`);
    const editor = page.locator(".tiptap"); await editor.waitFor();
    await editor.evaluate((el, { clipboard, source }) => {
      const transfer = new globalThis.DataTransfer(); for (const [mime, text] of Object.entries(clipboard)) transfer.setData(mime, text);
      el.dispatchEvent(source === "paste" ? new globalThis.ClipboardEvent("paste", { clipboardData: transfer, bubbles: true, cancelable: true })
        : new globalThis.DragEvent("drop", { dataTransfer: transfer, bubbles: true, cancelable: true }));
    }, { clipboard: fixture.clipboard, source });
    await page.waitForFunction(() => globalThis.document.querySelector("[data-math-node]"));
    const doc = await editor.evaluate((el) => el.editor.getJSON());
    if (JSON.stringify(doc) !== JSON.stringify(fixture.document)) throw new Error(`Wrong composer document: ${fixture.id} ${JSON.stringify(doc)}`);
    if (await editor.locator("a, script, img:not(.ProseMirror-separator), iframe, object, style, [onclick], [onerror], [src]").count() || await page.evaluate(() => Boolean(globalThis.__paste_injection))) throw new Error("Active HTML survived the paste");
    const evidence = await page.evaluate(() => globalThis.__jana_input_evidence);
    if (evidence.text !== fixture.serialised || evidence.sent.length || JSON.stringify(evidence.blocks) !== JSON.stringify([{ type: "text", text: fixture.serialised }])) throw new Error(`Wrong normalized payload: ${fixture.id}`);
    const audit = await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    if (audit.violations.length) throw new Error(JSON.stringify(audit.violations.map((v) => v.id)));
    results.push({ theme, source, fixture: fixture.id, doc, evidence, violations: 0 });
    if (!mutationDetected) {
      const request = page.waitForRequest("https://invalid.example/paste-mutation-control");
      await page.evaluate(() => { const image = globalThis.document.createElement("img"); image.src = "https://invalid.example/paste-mutation-control"; globalThis.document.body.append(image); });
      await request;
    }
    await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, egress, mutation_detected: mutationDetected, synthetic: true, os_clipboard_qualified: false }, null, 2));
if (results.length !== fixtures.length * 4 || errors.length || egress.length || !mutationDetected) { console.error(JSON.stringify({ errors, egress })); process.exitCode = 1; }
