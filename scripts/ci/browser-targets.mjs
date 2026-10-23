import { chromium } from "playwright";
import { readdir, readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { targetAudit } from "./target-audit.mjs";
import { fixtureServer } from "./browser-fixtures.mjs";
import { parseArgs } from "./performance-evidence.mjs";
const args = parseArgs(process.argv.slice(2)); const out = path.resolve(args.out ?? "dist/gallery-targets");
const states = [];
for (const file of (await readdir("packages/ui/gallery/states")).sort()) {
  if (!file.endsWith(".json")) continue;
  const state = JSON.parse(await readFile(`packages/ui/gallery/states/${file}`, "utf8"));
  if (!args.components || args.components.split(",").includes(state.component)) states.push(state);
}
const selected = args.limit ? states.slice(0, Number(args.limit)) : states;
const server = await fixtureServer(); const browser = await chromium.launch();
const results = [], errors = [], probes = []; let mutation = false;
try {
  const cases = [];
  for (const state of selected) for (const theme of (args.themes ?? "light,dark").split(",")) for (const scale of (args.scales ?? "1,1.5").split(",")) for (const width of (args.widths ?? "1366,800").split(",").map(Number)) cases.push({ state, theme, scale, width });
  let index = 0;
  await Promise.all(Array.from({ length: Math.min(4, cases.length) }, async () => {
    const page = await browser.newPage({ reducedMotion: "reduce" }); page.setDefaultTimeout(15000);
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
    while (index < cases.length) {
      const { state, theme, scale, width } = cases[index++];
      await page.setViewportSize({ width, height: 768 });
      await page.goto(`${server.url}/gallery.html?state=${encodeURIComponent(state.id)}&theme=${theme}&scale=${scale}`);
      const fixture = page.locator("[data-gallery-id]"); await fixture.waitFor();
      await page.evaluate(() => globalThis.document.fonts.ready);
      if (state.component === "Settings" && state.state === "canonical") await fixture.locator("[data-settings-section]").first().waitFor();
      const audit = await fixture.evaluate(targetAudit);
      results.push({ name: `${state.id}/${theme}/${scale}/${width}`, ...audit });
      if (args["self-test"] && !mutation) {
        mutation = true;
        await fixture.evaluate((root) => { const b = globalThis.document.createElement("button"); b.textContent = "INJECTED SMALL TARGET"; b.id = "target-mutation"; const style = globalThis.document.createElement("style"); style.textContent = "#target-mutation::after { width:10px!important;height:10px!important;inset:0!important;transform:none!important }"; root.append(style); b.style.cssText = "width:10px!important;height:10px!important;min-width:0!important;min-height:0!important;padding:0!important"; root.append(b); });
        const seeded = await fixture.evaluate(targetAudit);
        mutation = seeded.small.some((r) => r.text === "INJECTED SMALL TARGET");
        if (!mutation) throw new Error("Small-target self-test was not detected");
      }
      if (results.length % 100 === 0) console.log(`${results.length}/${cases.length} target cases`);
    }
    await page.close();
  }));
  const probe = await browser.newPage(); probe.setDefaultTimeout(15000);
  for (const width of [800, 1366]) {
    await probe.setViewportSize({ width, height: 768 });
    await probe.goto(`${server.url}/gallery.html?state=visual-viewer.canonical.bearing-diagram-hidden`);
    const part = probe.locator('[data-part="P"][role="button"]'); await part.waitFor(); await part.scrollIntoViewIfNeeded();
    const hit = await probe.locator('[data-part-overlay-for="P"]').boundingBox();
    if (!hit || hit.width < 43.9 || hit.height < 43.9) throw new Error("SVG hit area was not expanded");
    await probe.mouse.click(hit.x + hit.width / 2 + 17, hit.y + hit.height / 2);
    await probe.locator('[data-visual-part-panel="P"]').waitFor();
    probes.push({ kind: "svg-transparent-extension", width, pass: true });
  }
  await probe.goto(`${server.url}/gallery.html?state=tutor-turn.canonical`);
  const disclosure = probe.locator("button[aria-expanded]").first(); await disclosure.waitFor();
  const drawn = await disclosure.boundingBox();
  await probe.mouse.click(drawn.x + drawn.width / 2, drawn.y + drawn.height + 2);
  if (await disclosure.getAttribute("aria-expanded") !== "true") throw new Error("Compact button extension did not receive the click");
  probes.push({ kind: "compact-button-extension", pass: true }); await probe.close();
  await mkdir(out, { recursive: true });
  const failed = results.filter((r) => r.small.length);
  const report = { test: "dsn17_target_size", cases: results.length, checked: results.reduce((sum, r) => sum + r.checked, 0), failures: failed.length, errors, self_test: mutation, physical_probes: probes, synthetic: true, native_webviews: false, results };
  await writeFile(path.join(out, "targets.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ out, cases: results.length, failures: failed.length, errors: errors.length }));
  if (!results.length || failed.length || errors.length) process.exitCode = 1;
} finally { await browser.close(); await server.close(); }
