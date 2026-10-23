// Keyboard-only S2 journeys against the real App and a synthetic, local core. No camera or model qualification.
import { chromium } from "playwright";
import { PNG } from "pngjs";
import { createServer } from "../../apps/desktop/node_modules/vite/dist/node/index.js";
import react from "../../apps/desktop/node_modules/@vitejs/plugin-react/dist/index.js";
import tailwindcss from "../../apps/desktop/node_modules/@tailwindcss/vite/dist/index.mjs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
const out = path.resolve(process.argv[2] ?? "dist/keyboard-flows"); await mkdir(out, { recursive: true });
const server = await createServer({ root: path.resolve("apps/desktop"), configFile: false, plugins: [react(), tailwindcss()], server: { host: "127.0.0.1", port: 0 } });
await server.listen(); const browser = await chromium.launch(); const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const results = [], errors = []; let page;
const check = (condition, message) => { if (!condition) throw new Error(message); };
try {
  await context.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" || route.request().url().startsWith("data:") ? route.continue() : route.abort());
  for (const flow of ["snap-and-solve", "stuck-in-practice", "exam-rehearsal", "fix-weak-topic"]) {
    page = await context.newPage(); page.setDefaultTimeout(15000);
    await page.addInitScript(() => { globalThis.__pointerActions = 0; globalThis.document.addEventListener("pointerdown", () => { globalThis.__pointerActions++; }, true); });
    page.on("pageerror", (error) => errors.push({ flow, message: error.message }));
    await page.goto(`${server.resolvedUrls.local[0]}gallery.html?benchmark=keyboard-flows`);
    let tabs = 0;
    const tabTo = async (target) => {
      await target.waitFor({ state: "visible" });
      for (let i = 0; i < 250; i++) {
        if (await target.evaluate((el) => el === globalThis.document.activeElement)) return;
        await page.keyboard.press("Tab"); tabs++;
      }
      throw new Error(`Cannot reach ${await target.evaluate((el) => el.outerHTML)} by Tab`);
    };
    const activate = async (target, key = "Enter") => { await tabTo(target); await page.keyboard.press(key); };
    const chooseRadio = async (name) => {
      const target = page.getByRole("radio", { name, exact: true }); await target.waitFor();
      const selector = `input[type="radio"][name=${JSON.stringify(await target.getAttribute("name"))}]`;
      const group = page.locator(selector), checked = page.locator(`${selector}:checked`);
      await tabTo(await checked.count() ? checked : group.first());
      // Native radio groups have one Tab stop; arrows choose the other options.
      for (let i = 0; i < await group.count(); i++) {
        if (await target.evaluate((el) => el === globalThis.document.activeElement)) { await page.keyboard.press("Space"); return; }
        await page.keyboard.press("ArrowRight");
      }
      throw new Error(`Cannot choose radio ${name} by keyboard`);
    };
    const button = (name) => page.getByRole("button", { name, exact: true });
    const evidence = () => page.evaluate(() => globalThis.__jana_keyboard_evidence);
    await activate(page.getByRole("button", { name: /^Ada/ }));
    await page.getByRole("navigation", { name: "Main" }).waitFor();
    if (flow === "snap-and-solve") {
      await activate(button("Photo of a question"));
      const chosen = page.waitForEvent("filechooser");
      await activate(button("Choose photo"));
      const image = new PNG({ width: 900, height: 700 }); image.data.fill(255);
      // The OS file picker is the single explicit boundary; all in-app controls use Tab/Enter/Space.
      await (await chosen).setFiles({ name: "synthetic-question.png", mimeType: "image/png", buffer: PNG.sync.write(image) });
      await button("Crop corner 1").waitFor();
      await tabTo(button("Crop corner 1")); await page.keyboard.press("ArrowRight");
      await activate(button("Use this area"));
      await page.getByText("Is this the question?", { exact: true }).waitFor();
      check(!(await evidence()).log.some((r) => r.method === "POST" && r.path.endsWith("/turns")), "Photo started a turn before confirmation");
      await activate(button("Yes, that's it"));
      await page.waitForFunction(() => globalThis.__jana_keyboard_evidence.log.some((r) => r.method === "POST" && r.path.endsWith("/turns")));
      await page.locator('[data-mode="guided"]').waitFor();
      const e = await evidence();
      check(e.log.some((r) => r.path.endsWith("/confirm")), "Photo was not confirmed");
      check(e.log.some((r) => r.method === "POST" && r.path.endsWith("/turns") && r.body.intent === "ask"), "Confirmed photo did not open the tutor");
    } else if (flow === "stuck-in-practice") {
      await page.keyboard.press("Control+3");
      await chooseRadio("Other 1");
      await activate(button("Check my answer"));
      await page.locator('[data-verdict="incorrect"]').waitFor();
      await activate(button("Give me a hint").first());
      await activate(button("Back to practice question 1"));
      check(await page.getByRole("radio", { name: "Other 1", exact: true }).isChecked(), "Practice draft was lost");
      check((await evidence()).log.some((r) => r.method === "POST" && r.path.endsWith("/answers")), "No practice attempt was submitted");
      check((await evidence()).helped.length === 1, "Help did not load the practice item");
    } else if (flow === "exam-rehearsal") {
      await page.keyboard.press("Control+4");
      await activate(button("Choose this paper")); await activate(button("Start"));
      await chooseRadio("Right 1");
      await page.keyboard.press("Alt+ArrowRight");
      await chooseRadio("Other 2");
      await page.keyboard.press("Control+Enter");
      await activate(page.getByRole("alertdialog").getByRole("button", { name: "Submit", exact: true }));
      await page.getByRole("heading", { name: "1 out of 3", exact: true }).waitFor();
      await activate(page.locator('[data-review-question="2"]').getByRole("button", { name: "Show me why", exact: true }));
      await activate(button("Back to the mock report"));
      await activate(button("Practise these topics"));
      await page.getByRole("heading", { name: "Today's practice", exact: true }).waitFor();
      const e = await evidence(); check(e.reviewed.length === 1, "Review did not load question 2");
      check(e.log.some((r) => r.method === "GET" && /^\/v1\/practice\/sets\/set_/.test(r.path)), "Targeted set was not opened");
    } else {
      await page.keyboard.press("Control+2");
      await activate(page.locator("[data-topic-id]").first());
      await activate(page.getByRole("dialog").getByRole("button", { name: /Start the lesson/ }));
      for (let i = 0; i < 7; i++) await activate(button("Next"));
      await activate(button("Finish"));
      await activate(button("Practise this topic"));
      await page.getByRole("heading", { name: "Today's practice", exact: true }).waitFor();
      const e = await evidence(); const started = e.log.findLast((r) => r.method === "POST" && r.path === "/v1/practice/sets");
      check(JSON.stringify(started?.body.kc_ids) === JSON.stringify(e.lessonKcs), "Practice did not target the completed lesson's KCs");
    }
    const pointers = await page.evaluate(() => globalThis.__pointerActions);
    check(pointers === 0, "A journey used pointer input");
    results.push({ flow, pass: true, tabs, pointer_actions: pointers }); console.log(`${flow}: pass (${tabs} Tabs)`);
    await page.close(); page = undefined;
  }
} catch (error) {
  if (page) { await writeFile(path.join(out, "evidence.json"), JSON.stringify(await page.evaluate(() => globalThis.__jana_keyboard_evidence))); await page.screenshot({ path: path.join(out, "failure.png") }); await writeFile(path.join(out, "failure.html"), await page.content()); }
  errors.push({ message: error.message });
} finally {
  await writeFile(path.join(out, "result.json"), JSON.stringify({ test: "loc12_keyboard_only_flows", synthetic: true, hardware: false, model_qualification: false, file_picker: "synthetic upload at OS boundary", results, errors }, null, 2));
  await browser.close(); await server.close();
}
if (results.length !== 4 || errors.length) { console.error(JSON.stringify(errors)); process.exitCode = 1; }
