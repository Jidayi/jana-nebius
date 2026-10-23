import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";
const root = path.resolve(import.meta.dirname, "../../..");
test("loc21_maths_input_parity", async () => {
  const out = await mkdtemp(path.join(tmpdir(), "jana-input-keys-")), run = promisify(execFile);
  await run(process.execPath, ["node_modules/vite/bin/vite.js", "build", "--config", "benchmark.config.ts"], { cwd: path.join(root, "apps/desktop"), timeout: 60000 });
  let failure: unknown;
  try { await run(process.execPath, ["scripts/ci/browser-input-keys.mjs", out], { cwd: root, timeout: 120000 }); } catch (error) { failure = error; }
  const result = JSON.parse(await readFile(path.join(out, "result.json"), "utf8"));
  expect(result.errors, `Evidence: ${out}`).toEqual([]); expect(result.results).toHaveLength(10);
  for (const theme of ["light", "dark"]) expect(result.results.filter((r: { theme: string }) => r.theme === theme).map((r: { count: number }) => r.count)).toEqual([24, 25, 22, 9, 14]);
  expect(failure).toBeUndefined();
}, 185000);
