// DOM geometry in Chromium; supported webview/OS zoom and independent visual review stay separate.
import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";
import { STATES } from "@jana/ui/gallery";
const root = path.resolve(import.meta.dirname, "../../..");
test("loc17_text_scale_150", async () => {
  const output = await mkdtemp(path.join(tmpdir(), "jana-gallery-scale-")), run = promisify(execFile);
  await run(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--config", "benchmark.config.ts"], { cwd: path.join(root, "apps/desktop"), timeout: 60000 });
  let failure: unknown;
  try { await run(process.execPath, ["scripts/ci/browser-accessibility.mjs", `--out=${output}`, "--scales=1.5", "--widths=1366,800", "--screenshots=none", "--layout-self-test"], { cwd: root, timeout: 1200000 }); }
  catch (error) { failure = error; }
  const report = JSON.parse(await readFile(path.join(output, "audit.json"), "utf8"));
  expect(report.cases).toBe(STATES.length * 4);
  expect(new Set(report.results.map((r: { name: string }) => r.name))).toEqual(new Set(STATES.flatMap((s) => ["light", "dark"].flatMap((theme) => [1366, 800].map((width) => `${s.id}--${theme}--1.5--${width}`)))));
  expect(report.results.filter((r: { layout: { clipped: unknown[]; overlaps: unknown[]; horizontal_overflow: boolean; scale_applied: boolean } }) => r.layout.clipped.length || r.layout.overlaps.length || r.layout.horizontal_overflow || !r.layout.scale_applied), `Report: ${output}/audit.json`).toEqual([]);
  expect(report.console_errors).toEqual([]); expect(report.failures).toBe(0);
  expect(report.layout_mutation_detected).toBe(true); expect(failure).toBeUndefined();
}, 1270000);
