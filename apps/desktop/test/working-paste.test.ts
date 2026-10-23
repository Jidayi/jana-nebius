import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";
const root = path.resolve(import.meta.dirname, "../../..");
test("inp12_paste_splits_lines: browser paste handler and native submission", async () => {
  const out = await mkdtemp(path.join(tmpdir(), "jana-working-paste-")), run = promisify(execFile);
  await run(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--config", "benchmark.config.ts"], { cwd: path.join(root, "apps/desktop"), timeout: 60000 });
  let failure: unknown;
  try { await run(process.execPath, ["scripts/ci/browser-working-paste.mjs", out], { cwd: root, timeout: 120000 }); } catch (error) { failure = error; }
  const result = JSON.parse(await readFile(path.join(out, "result.json"), "utf8"));
  expect(result.errors, `Evidence: ${out}`).toEqual([]); expect(result.results).toHaveLength(2);
  expect(result.results.every((r: { paste_event_synthetic: boolean; keyboard_submit_native: boolean; violations: number }) => r.paste_event_synthetic && r.keyboard_submit_native && r.violations === 0)).toBe(true);
  expect(failure).toBeUndefined();
}, 185000);
