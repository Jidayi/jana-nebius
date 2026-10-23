// Automated gallery checks; manual WCAG and native assistive-technology review remain external.
import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";
import { STATES } from "@jana/ui/gallery";

const root = path.resolve(import.meta.dirname, "../../..");
test("loc11_axe_gallery", async () => {
  const output = await mkdtemp(path.join(tmpdir(), "jana-gallery-axe-"));
  const run = promisify(execFile);
  await run(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--config", "benchmark.config.ts"], { cwd: path.join(root, "apps/desktop"), timeout: 60000 });
  // Preserve the report on non-zero exit so an assertion identifies the actual failed cases.
  let failure: unknown;
  try { await run(process.execPath, ["scripts/ci/browser-accessibility.mjs", `--out=${output}`, "--scales=1", "--widths=1366", "--screenshots=none", "--axe-self-test"], { cwd: root, timeout: 1200000 }); }
  catch (error) { failure = error; }
  const report = JSON.parse(await readFile(path.join(output, "audit.json"), "utf8"));
  expect(report.selected_fixtures).toBe(STATES.length);
  expect(report.cases).toBe(STATES.length * 2);
  expect(new Set(report.results.map((r: { name: string }) => r.name))).toEqual(new Set(STATES.flatMap((s) => ["light", "dark"].map((theme) => `${s.id}--${theme}--1--1366`))));
  expect(report.results.filter((r: { violations: unknown[] }) => r.violations.length), `Report: ${output}/audit.json`).toEqual([]);
  expect(report.console_errors).toEqual([]);
  expect(report.failures).toBe(0);
  expect(report.axe_mutation_detected).toBe(true);
  expect(failure).toBeUndefined();
}, 1270000);
