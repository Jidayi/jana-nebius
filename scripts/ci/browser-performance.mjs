// Run against a separately built synthetic entry. No learner data or model is used.
import { chromium } from "playwright";
import { readFile, readdir, mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { cpus, platform, arch } from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { PROFILE, evidenceFailures, qualificationGaps, parseArgs } from "./performance-evidence.mjs";
import { fixtureServer } from "./browser-fixtures.mjs";

const args = parseArgs(process.argv.slice(2));
const output = path.resolve(args.out ?? "dist/browser-performance");
const digest = (data) => createHash("sha256").update(data).digest("hex");
async function sourceDigest() {
  const hash = createHash("sha256");
  const walk = async (dir) => {
    for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(file);
      else { hash.update(file); hash.update(await readFile(file)); }
    }
  };
  for (const dir of ["apps/desktop/src", "apps/desktop/gallery", "packages/ui/src", "packages/ui/assets", "packages/client-core/src", "packages/contracts-ts/src", "packages/renderers/src", "packages/i18n/src", "packages/i18n/locales"]) await walk(dir);
  for (const file of ["pnpm-lock.yaml", "apps/desktop/vite.config.ts", "apps/desktop/benchmark.config.ts", "scripts/ci/browser-performance.mjs", "scripts/ci/browser-fixtures.mjs", "scripts/ci/performance-evidence.mjs"]) hash.update(await readFile(file));
  return hash.digest("hex");
}
const server = await fixtureServer();
const browser = await chromium.launch({ headless: true });
try {
  const runner = { os: platform(), arch: arch(), cpu: cpus()[0].model, cores: cpus().length, browser: browser.version() };
  const runnerSha = digest(JSON.stringify(runner));
  const sourceSha = await sourceDigest();
  const baseline = args.baseline ? JSON.parse(await readFile(args.baseline, "utf8")) : null;
  const calibration = args.calibration ? JSON.parse(await readFile(args.calibration, "utf8")) : null;
  await mkdir(output, { recursive: true });
  async function replay(slow) {
    const page = await browser.newPage({ viewport: PROFILE.viewport, reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (["error", "warning"].includes(m.type())) errors.push(m.text()); });
    const client = await page.context().newCDPSession(page);
    await client.send("Emulation.setCPUThrottlingRate", { rate: PROFILE.cpu_rate });
    // Block everything except this local static fixture server.
    await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
    await page.goto(`${server.url}/gallery.html?benchmark=transcript${slow ? "&slow-board" : ""}`);
    await page.evaluate(() => globalThis.document.fonts.ready);
    const editor = page.locator('[contenteditable="true"]').first();
    await editor.waitFor();
    await page.getByRole("log").evaluate((el) => { el.scrollTop = 0; });
    // Settle font/maths/layout and the first mounted window before observing.
    await page.waitForTimeout(2000);
    await page.getByRole("button", { name: "Replay 5,000 deltas" }).click();
    await editor.focus();
    // Real keyboard events, interleaved with the full replay, rather than synthetic DOM events.
    for (let i = 0; i < 50; i++) {
      if (await page.locator("[data-performance-report]").count()) break;
      await page.keyboard.type(String.fromCharCode(97 + i % 26));
      await page.waitForTimeout(250);
    }
    await page.locator("[data-performance-report]").waitFor({ timeout: 60000 });
    const sample = JSON.parse(await page.locator("[data-performance-report]").textContent());
    const report = { schema: 1, created_at: new Date().toISOString(), commit: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(), source_sha256: sourceSha,
      candidate_acceptance: false, reference_hardware: false, profile: PROFILE, runner, runner_sha256: runnerSha, sample, console_errors: errors };
    report.failures = evidenceFailures(report, slow ? null : baseline);
    report.qualification_gaps = qualificationGaps(report, baseline, calibration);
    await page.screenshot({ path: path.join(output, slow ? "slow-board.png" : "replay.png") });
    await writeFile(path.join(output, slow ? "slow-board.json" : "replay.json"), `${JSON.stringify(report, null, 2)}\n`);
    await page.close();
    return report;
  }
  const observed = await replay(false);
  let failures = observed.failures;
  if (args["self-test"] !== undefined) {
    const mutated = await replay(true);
    if (!mutated.failures.some((f) => f.startsWith("max_long_task_ms:") || f.startsWith("frame_p95_ms:"))) failures = [...failures, "Slow board mutation was not detected."];
  }
  console.log(JSON.stringify({ output, failures, qualification_gaps: observed.qualification_gaps }, null, 2));
  if (failures.length || (args["require-qualified"] !== undefined && observed.qualification_gaps.length)) process.exitCode = 1;
} finally {
  await browser.close();
  await server.close();
}
