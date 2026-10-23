import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";
const root = path.resolve(import.meta.dirname, "../../..");
test("inp07_parse_error_hints: real browser markers and invalid blur retention", async () => {
  const out = await mkdtemp(path.join(tmpdir(), "jana-input-errors-")), run = promisify(execFile);
  await run(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--config", "benchmark.config.ts"], { cwd: path.join(root, "apps/desktop"), timeout: 60000 });
  let failure: unknown;
  try { await run(process.execPath, ["scripts/ci/browser-input-errors.mjs", out], { cwd: root, timeout: 120000 }); } catch (error) { failure = error; }
  const result = JSON.parse(await readFile(path.join(out, "result.json"), "utf8"));
  expect(result.errors, `Evidence: ${out}`).toEqual([]); expect(result.results).toHaveLength(12);
  expect(result.results.every((r: { dotted: string; violations: number }) => r.dotted === "dotted" && r.violations === 0)).toBe(true);
  expect(failure).toBeUndefined();
}, 185000);
