import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext();
const errors = [], results = [], reasons = ["voice.microphone_missing", "voice.microphone_denied", "voice.microphone_unavailable", "voice.too_noisy"];
try {
  for (const reason of reasons) for (const theme of ["light", "dark"]) for (const width of [800, 1366]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000); page.on("pageerror", (e) => errors.push(e.message)); await page.setViewportSize({ width, height: 900 });
    await page.goto(`${server.url}/gallery.html?benchmark=microphone-flows&theme=${theme}&reason=${reason}`);
    const editor = page.getByRole("textbox", { name: "Message to the tutor" }); await editor.click(); await page.keyboard.type("Keep my draft");
    await page.getByRole("button", { name: "Hold to dictate" }).focus(); await page.keyboard.down("Space");
    await page.waitForFunction(() => globalThis.__jana_microphone_evidence.dictation === "listening"); await page.keyboard.up("Space");
    await page.getByRole("button", { name: "Simulate microphone error" }).click();
    await page.waitForFunction((reason) => globalThis.__jana_microphone_evidence.dictation === "idle" && globalThis.__jana_microphone_evidence.error === reason, reason);
    assert.equal(await editor.innerText(), "Keep my draft"); assert(await editor.isEditable());
    await editor.click(); await page.keyboard.press("End"); await page.keyboard.type(" after error"); await page.keyboard.press("Space"); await page.keyboard.type("typed");
    assert.equal(await editor.innerText(), "Keep my draft after error typed");
    assert.equal(await page.evaluate(() => globalThis.__jana_microphone_evidence.sent.length), 0);
    const audit = await new AxeBuilder({ page }).include("[data-microphone-flow]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze(); assert.deepEqual(audit.violations.map((v) => v.id), []);
    await page.keyboard.press("Enter");
    const evidence = await page.evaluate(() => globalThis.__jana_microphone_evidence);
    assert.equal(evidence.sent.length, 1); assert.equal(evidence.sent[0].capture.text, "Keep my draft after error typed"); assert.equal(evidence.sent[0].capture.source, "typed"); assert.equal(evidence.sent[0].intent, "ask"); assert(evidence.released > 0);
    results.push({ reason, theme, width, real_keyboard_input: true, draft_preserved: true, violations: 0 }); await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic_audio_and_core: true, native_hardware_evidence: false }, null, 2));
if (results.length !== 16 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
