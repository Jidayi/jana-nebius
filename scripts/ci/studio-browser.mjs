/* global document, getComputedStyle */
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = fileURLToPath(new URL("../../", import.meta.url));
const out = path.resolve(process.argv.find((s) => s.startsWith("--out="))?.slice(6) ?? "dist/studio-browser");
await mkdir(out, { recursive: true });
const temporary = await mkdtemp(path.join(os.tmpdir(), "jana-studio-browser-")), workspace = path.join(temporary, "workspace"), authors = path.join(temporary, "authors");
const python = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
execFileSync(python, ["-c", `import importlib.util,sys\nfrom pathlib import Path\nspec=importlib.util.spec_from_file_location('studio_fixture',sys.argv[1])\nm=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\nm.fixture(Path(sys.argv[2]))\nm.Accounts(Path(sys.argv[3])).create('lead','Synthetic Lead','lead@example.test',['curriculum_lead'])`, path.join(root, "scripts/packaging/studio-smoke.py"), workspace, authors], { cwd: root });
const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5191", "--strictPort"], { cwd: path.join(root, "apps/studio"), env: { ...process.env, JANA_STUDIO_WORKSPACE: workspace, JANA_AUTHORING_HOME: authors, JANA_AUTHOR: "lead", JANA_STUDIO_EVAL_URL: "", JANA_STUDIO_EVAL_MODEL: "" }, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = ""; server.stdout.on("data", (b) => { serverLog += b; }); server.stderr.on("data", (b) => { serverLog += b; });
let browser, page;
const errors = [], audits = [], journeys = [];
try {
  let ready = false;
  for (let n = 0; n < 120; n++) { try { const r = await fetch("http://127.0.0.1:5191"); if (r.ok) { ready = true; break; } } catch { /* Wait for this test's server. */ } await new Promise((r) => setTimeout(r, 250)); }
  assert(ready, serverLog);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, reducedMotion: "reduce" });
  page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e))); page.on("console", (m) => { if (["error", "warning"].includes(m.type())) errors.push(m.text()); });
  await page.goto("http://127.0.0.1:5191");
  await page.getByRole("button", { name: "Open local workspace", exact: true }).click();
  await page.getByRole("navigation", { name: "Content types" }).getByRole("button", { name: /^Items/ }).click();
  await page.getByRole("button", { name: /A cyclist rides 1200 m/ }).click();
  await page.getByLabel("Candidate answer").fill("8.0 m/s");
  await page.getByRole("button", { name: "Run marker", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll("pre")].some((e) => e.textContent.includes('"outcome": "correct"')));
  journeys.push("open-workspace-and-production-marker");
  await page.getByRole("navigation", { name: "Content types" }).getByRole("button", { name: /^Misconceptions/ }).click();
  await page.getByRole("button", { name: /mc\.phy\.o\.time_over_distance/ }).click();
  await page.getByRole("button", { name: "Run signature bench" }).click();
  await page.getByRole("region", { name: "Signature test bench", exact: true }).getByText("Run completed", { exact: true }).waitFor();
  journeys.push("signature-bench-on-real-workspace");
  await page.getByText(/^Comments ·/).click();
  await page.getByLabel("Author comment").fill("Check this explanation before publication.");
  await page.getByLabel("Blocks publication").check();
  await page.getByRole("button", { name: "Add comment", exact: true }).click();
  await page.getByRole("button", { name: "Resolve comment", exact: true }).waitFor();
  await page.getByRole("button", { name: "Queue publication", exact: true }).click();
  await page.getByRole("listitem").filter({ hasText: "Open blocking comment:" }).first().waitFor();
  await page.getByRole("button", { name: "Resolve comment", exact: true }).click();
  await page.getByText("Blocking · resolved", { exact: true }).waitFor();
  journeys.push("blocking-comment-refusal-and-resolution");

  const audit = async (name, selector) => {
    const results = await new AxeBuilder({ page }).include(selector).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const layout = await page.locator(selector).evaluate((root) => ({ horizontal_overflow: root.scrollWidth > root.clientWidth + 2, font: getComputedStyle(root.querySelector("h1") ?? root).fontSize }));
    audits.push({ name, violations: results.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })), layout });
    await page.locator(selector).screenshot({ path: path.join(out, `${name}.png`) });
    assert.equal(results.violations.length, 0, JSON.stringify(audits.at(-1))); assert(!layout.horizontal_overflow, `${name}: horizontal overflow`);
  };
  await audit("workspace-review", "main.editor-area");
  await page.getByRole("button", { name: "Edit skills", exact: true }).click();
  await page.getByLabel("Skill", { exact: true }).selectOption("agent-diagnose-question");
  await page.getByLabel("Complete skill source").waitFor();
  for (const theme of ["light", "dark"]) for (const scale of [1, 1.5]) {
    await page.evaluate(({ theme, scale }) => { document.documentElement.dataset.theme = theme; document.documentElement.style.setProperty("--text-scale", String(scale)); }, { theme, scale });
    await audit(`skill-${theme}-${scale}`, "dialog[open]");
  }
  journeys.push("skill-editor-shared-contract-and-lint");
  await page.getByRole("button", { name: "Close skill editor" }).click();
  await page.getByRole("button", { name: "Manage diagrams", exact: true }).click();
  await page.getByLabel("Diagram", { exact: true }).selectOption("dgm.phy.plane_mirror_reflection.v1");
  await page.getByLabel("SVG source").waitFor();
  await page.getByRole("heading", { name: "Production preview", exact: true }).waitFor();
  for (const theme of ["light", "dark"]) for (const scale of [1, 1.5]) {
    await page.evaluate(({ theme, scale }) => { document.documentElement.dataset.theme = theme; document.documentElement.style.setProperty("--text-scale", String(scale)); }, { theme, scale });
    await audit(`diagram-${theme}-${scale}`, "dialog[open]");
  }
  journeys.push("safe-diagram-editor-and-production-preview");
  await page.getByRole("button", { name: "Close diagram manager" }).click();
  await page.getByRole("button", { name: "Import content", exact: true }).click();
  await page.getByLabel("Import source", { exact: true }).fill("- external_ref: synthetic-unfinished-row\n");
  await page.getByRole("button", { name: "Run import dry run" }).click();
  await page.getByRole("heading", { name: "Fix import errors", exact: true }).waitFor();
  await audit("import-rejected-row", "dialog[open]");
  journeys.push("licensed-import-error-by-row");
  assert.equal(errors.length, 0, JSON.stringify(errors));
} catch (error) { errors.push(String(error)); process.exitCode = 1; if (page) { await writeFile(path.join(out, "failure.html"), await page.content()); await page.screenshot({ path: path.join(out, "failure.png") }); } }
finally {
  if (browser) await browser.close(); server.kill("SIGTERM");
  await writeFile(path.join(out, "audit.json"), JSON.stringify({ candidate_acceptance: false, fixture: "disposable fictional workspace", workspace, journeys, audits, errors, external: ["native webviews and screen readers", "visual baseline approval", "signed installer/device evidence", "real local-model and calibrated-judge observations"] }, null, 2) + "\n");
  await writeFile(path.join(out, "server.log"), serverLog);
}
console.log(JSON.stringify({ out, journeys: journeys.length, audits: audits.length, errors }));
