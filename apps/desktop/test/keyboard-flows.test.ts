import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";

test("loc12_keyboard_only_flows", async () => {
  const out = await mkdtemp(path.join(tmpdir(), "jana-keyboard-flows-"));
  let failure: unknown;
  try { await promisify(execFile)(process.execPath, ["scripts/ci/browser-keyboard-flows.mjs", out], { cwd: path.resolve(import.meta.dirname, "../../.."), timeout: 240000 }); }
  catch (error) { failure = error; }
  const result = JSON.parse(await readFile(path.join(out, "result.json"), "utf8"));
  expect(result.errors, `Evidence: ${out}`).toEqual([]);
  expect(result.results.map((r: { flow: string }) => r.flow)).toEqual(["snap-and-solve", "stuck-in-practice", "exam-rehearsal", "fix-weak-topic"]);
  expect(result.results.every((r: { pass: boolean; tabs: number; pointer_actions: number }) => r.pass && r.tabs > 0 && r.pointer_actions === 0)).toBe(true);
  expect(failure).toBeUndefined();
}, 250000);
