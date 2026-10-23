import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fixtureServer } from "./browser-fixtures.mjs";
import { parseArgs } from "./performance-evidence.mjs";
import { visualDiff } from "./visual-diff.mjs";
import { layoutAudit } from "./layout-audit.mjs";
import { targetAudit } from "./target-audit.mjs";

const args = parseArgs(process.argv.slice(2)), out = path.resolve(args.out ?? "dist/gallery-audit");
await mkdir(path.join(out, "screenshots"), { recursive: true });
const states = [];
for (const file of (await readdir("packages/ui/gallery/states")).sort()) {
  if (!file.endsWith(".json")) continue;
  const state = JSON.parse(await readFile(`packages/ui/gallery/states/${file}`, "utf8"));
  if ((!args.components || args.components.split(",").includes(state.component)) && (!args.states || args.states.split(",").includes(state.id))) states.push(state);
}
const selected = args.limit ? states.slice(0, Number(args.limit)) : states;
const server = await fixtureServer(), browser = await chromium.launch();
const results = [], consoleErrors = [], missingBaselines = [];
let mutation = null, mutationStarted = false, axeMutation = null, layoutMutation = null;
try {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  async function check(page, state, theme, scale, width) {
    const name = `${state.id}--${theme}--${scale}--${width}`;
    await page.setViewportSize({ width, height: 768 });
    await page.goto(`${server.url}/gallery.html?state=${encodeURIComponent(state.id)}&theme=${theme}&scale=${scale}`);
    const fixture = page.locator("[data-gallery-id]"); await fixture.waitFor();
    await page.evaluate(() => globalThis.document.fonts.ready);
    if (state.component === "Settings" && state.state === "canonical") await fixture.locator("[data-settings-section]").first().waitFor();
    const audit = await new AxeBuilder({ page }).include("[data-gallery-id]").withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    const layout = await fixture.evaluate(layoutAudit);
    if (args["axe-self-test"] && axeMutation === null) {
      // Verify the same axe pipeline detects an inaccessible control, then remove it.
      axeMutation = false;
      await fixture.evaluate((root) => { const button = globalThis.document.createElement("button"); button.id = "axe-unlabelled-control"; root.append(button); });
      const seeded = await new AxeBuilder({ page }).include("#axe-unlabelled-control").withTags(["wcag2a", "wcag2aa"]).analyze();
      axeMutation = seeded.violations.some((v) => v.id === "button-name");
      await fixture.locator("#axe-unlabelled-control").evaluate((button) => button.remove());
    }
    if (args["layout-self-test"] && layoutMutation === null) {
      layoutMutation = false;
      await fixture.evaluate((root) => {
        const box = globalThis.document.createElement("div"); box.id = "layout-mutation"; box.style.cssText = "position:relative;width:160px;height:100px";
        for (const label of ["LAYOUT FIRST", "LAYOUT SECOND"]) { const b = globalThis.document.createElement("button"); b.textContent = label; b.style.cssText = "position:absolute;left:0;top:0;width:140px;height:44px"; box.append(b); }
        const cut = globalThis.document.createElement("div"); cut.textContent = "LAYOUT CLIPPED"; cut.style.cssText = "position:absolute;top:60px;height:2px;overflow:hidden;font-size:20px"; box.append(cut); root.append(box);
      });
      const seeded = await fixture.evaluate(layoutAudit);
      layoutMutation = seeded.overlaps.some((pair) => pair.first === "LAYOUT FIRST" && pair.second === "LAYOUT SECOND") && seeded.clipped.some((cut) => cut.text === "LAYOUT CLIPPED");
      await fixture.locator("#layout-mutation").evaluate((el) => el.remove());
    }
    // Use the shared physical-target measurement, including transparent hit extensions.
    layout.small = (await fixture.evaluate(targetAudit)).small;
    const png = args.screenshots === "none" ? null : await fixture.screenshot({ animations: "disabled" });
    if (png) await writeFile(path.join(out, "screenshots", `${name}.png`), png);
    if (png && args["self-test"] && !mutationStarted) {
      mutationStarted = true;
      const outside = page.getByRole("combobox", { name: "component", exact: true });
      const unchanged = await outside.screenshot();
      await fixture.evaluate((root) => root.style.setProperty("--color-paper", "#ff00ff"));
      const changed = await fixture.screenshot({ animations: "disabled" });
      const affected = visualDiff(png, changed), unaffected = visualDiff(unchanged, await outside.screenshot());
      mutation = { case: name, changed_fixture_ratio: affected.ratio, outside_fixture_ratio: unaffected.ratio,
        pass: affected.failure !== null && unaffected.failure === null };
      await writeFile(path.join(out, "token-mutation.diff.png"), affected.image);
      await fixture.evaluate((root) => root.style.removeProperty("--color-paper"));
    }
    let diff = null;
    if (png && args["baseline-dir"]) {
      let previous;
      try { previous = await readFile(path.join(args["baseline-dir"], `${name}.png`)); }
      catch (error) { if (error.code !== "ENOENT") throw error; missingBaselines.push(name); }
      if (previous) { const compared = visualDiff(previous, png); diff = { failure: compared.failure, ratio: compared.ratio }; if (compared.failure) await writeFile(path.join(out, "screenshots", `${name}.diff.png`), compared.image); }
    } else missingBaselines.push(name);
    results.push({ name, violations: audit.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })), layout, diff });
    if (results.length % 25 === 0) {
      console.log(`${results.length} gallery cases checked`);
      await writeFile(path.join(out, "partial.json"), `${JSON.stringify({ incomplete: true, results, console_errors: consoleErrors }, null, 2)}\n`);
    }
  }
  const cases = [];
  for (const state of selected) for (const theme of (args.themes ?? "light,dark").split(",")) for (const scale of (args.scales ?? "1,1.5").split(",")) for (const width of (args.widths ?? "1366,800").split(",").map(Number)) cases.push({ state, theme, scale, width });
  let next = 0;
  await context.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
  const worker = async () => {
    const page = await context.newPage();
    page.on("pageerror", (e) => consoleErrors.push({ url: page.url(), message: e.message }));
    page.on("console", (m) => { if (["error", "warning"].includes(m.type())) consoleErrors.push({ url: page.url(), message: m.text() }); });
    while (next < cases.length) {
      const current = cases[next++];
      await check(page, current.state, current.theme, current.scale, current.width);
    }
    await page.close();
  };
  await Promise.all(Array.from({ length: Math.min(4, cases.length) }, worker));
  results.sort((a, b) => a.name.localeCompare(b.name));
  const failures = results.filter((r) => r.violations.length || r.layout.clipped.length || r.layout.overlaps.length || r.layout.small.length || r.layout.horizontal_overflow || !r.layout.scale_applied || r.diff?.failure);
  const report = { candidate_acceptance: false, native_screen_readers: "External NVDA/VoiceOver and supported webview audit required", browser: browser.version(), selected_fixtures: selected.length, cases: results.length, console_errors: consoleErrors, failures: failures.length, visual_mutation: mutation, axe_mutation_detected: axeMutation, layout_mutation_detected: layoutMutation, screenshots_generated: args.screenshots !== "none", missing_visual_baselines: missingBaselines, results };
  await writeFile(path.join(out, "audit.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({ out, cases: results.length, failures: failures.length, console_errors: consoleErrors.length, unreviewed_screenshots: missingBaselines.length }));
  if (!results.length || failures.length || consoleErrors.length || (args["self-test"] && !mutation?.pass) || (args["axe-self-test"] && !axeMutation) || (args["layout-self-test"] && !layoutMutation) || (args["require-baseline"] && missingBaselines.length)) process.exitCode = 1;
} finally { await browser.close(); await server.close(); }
