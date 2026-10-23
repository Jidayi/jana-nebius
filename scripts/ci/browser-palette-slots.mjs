// Real browser keyboard events only. Synthetic gallery, not native-webview/AT qualification.
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
const out = path.resolve(process.argv[2]); await mkdir(out, { recursive: true });
const server = await fixtureServer(), browser = await chromium.launch(), context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
const results = [], errors = [];
try {
  for (const theme of ["light", "dark"]) {
    const page = await context.newPage(); page.setDefaultTimeout(5000);
    page.on("pageerror", (e) => errors.push(e.message));
    const url = `${server.url}/gallery.html?state=math-input.canonical&theme=${theme}`;
    const tabTo = async (target) => {
      for (let i = 0; i < 100; i++) { if (await target.evaluate((el) => el === globalThis.document.activeElement)) return; await page.keyboard.press("Tab"); }
      throw new Error("Unreachable control");
    };
    for (let tab = 0; tab < 5; tab++) {
      await page.goto(url); const editor = page.locator('.tiptap[contenteditable="true"]');
      await tabTo(editor); await page.keyboard.press("Alt+m");
      const tabs = page.getByRole("tab"); await tabs.first().waitFor();
      await page.waitForFunction(() => globalThis.document.activeElement?.matches('[role="tab"][aria-selected="true"]'));
      if (!await tabs.first().evaluate((el) => el === globalThis.document.activeElement)) throw new Error("Alt+M did not focus tabs");
      for (let n = 0; n < tab; n++) await page.keyboard.press("ArrowRight");
      const palette = page.locator("[data-entry-palette]");
      const box = await palette.boundingBox(), editBox = await editor.boundingBox();
      if (!box || !editBox || box.height > 180 || box.y < editBox.y + editBox.height || await palette.evaluate((el) => [...el.querySelectorAll("[role=toolbar]")].some((row) => row.scrollWidth > row.clientWidth + 1))) throw new Error(`Palette size/overlap ${JSON.stringify({box, editBox})}`);
      await page.keyboard.press("Tab"); const keys = page.getByRole("toolbar").getByRole("button"), count = await keys.count();
      const entries = await keys.evaluateAll((buttons) => buttons.map((button) => button.getAttribute("data-key") ?? button.textContent ?? ""));
      for (let index = 0; index < count; index++) {
        const key = keys.nth(index); await tabTo(key);
        const source = entries[index], slots = source.split("□").length - 1;
        await page.keyboard.press("Enter");
        if (slots) {
          const input = page.getByRole("textbox", { name: "Maths as typed", exact: true }); await input.waitFor();
          let expected = source;
          for (let slot = 0; slot < slots; slot++) {
            const selection = await input.evaluate((el) => ({ value: el.value, start: el.selectionStart, end: el.selectionEnd, focused: el === globalThis.document.activeElement }));
            const at = expected.indexOf("□");
            if (!selection.focused || selection.value !== expected || selection.start !== at || selection.end !== at + 1) throw new Error(`Wrong slot order: ${source} ${JSON.stringify(selection)}`);
            const value = tab === 4 ? "H2" : "2";
            await page.keyboard.insertText(value); expected = expected.replace("□", value);
            await page.keyboard.press("Tab");
          }
          await input.waitFor({ state: "detached" });
          await page.waitForFunction(() => globalThis.document.activeElement?.matches('.tiptap[contenteditable="true"]'));
        } else if (tab === 3 && index >= 6) {
          const template = ["Journal", "T-account", "Trial balance"][index - 6];
          const table = page.getByRole("table", { name: template, exact: true }); await table.waitFor();
          const cell = table.getByRole("textbox").first(); await tabTo(cell); await page.keyboard.insertText("test");
          if (await cell.inputValue() !== "test") throw new Error("Ledger key did not insert editable cells");
        }
        // Clear through the real editing surface, leaving no old nodes/inputs between operations.
        await page.keyboard.press("Escape"); await page.waitForFunction(() => globalThis.document.activeElement?.matches('.tiptap[contenteditable="true"]')); await tabTo(editor); await page.keyboard.press("ControlOrMeta+a"); await page.keyboard.press("Backspace");
        if (!await palette.count()) { await page.keyboard.press("Alt+m"); await page.waitForFunction(() => globalThis.document.activeElement?.matches('[role="tab"][aria-selected="true"]')); }
        // Select the same tab and the next key via native roving focus.
        await tabTo(tabs.nth(tab)); await page.keyboard.press("Tab");
        await page.keyboard.press("Home"); for (let n = 0; n < index + 1 && index + 1 < count; n++) await page.keyboard.press("ArrowRight");
      }
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => globalThis.document.activeElement?.matches('.tiptap[contenteditable="true"]'));
      if (await palette.count() || !await editor.evaluate((el) => el === globalThis.document.activeElement)) throw new Error("Escape from palette did not close/return focus");
      await page.keyboard.press("Alt+m"); await page.waitForFunction(() => globalThis.document.activeElement?.matches('[role="tab"][aria-selected="true"]')); await page.keyboard.press("Alt+m");
      await page.waitForFunction(() => globalThis.document.activeElement?.matches('.tiptap[contenteditable="true"]'));
      if (await palette.count() || !await editor.evaluate((el) => el === globalThis.document.activeElement)) throw new Error("Alt+M from palette did not close/return focus");
      results.push({ theme, tab, entries, count, height: box.height, keyboard_only: true });
    }
    await page.close();
  }
} catch (error) { errors.push(error.stack ?? error.message); }
finally { await browser.close(); await server.close(); }
await writeFile(path.join(out, "result.json"), JSON.stringify({ results, errors, synthetic: true, native_assistive_technology: false }, null, 2));
if (results.length !== 10 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
