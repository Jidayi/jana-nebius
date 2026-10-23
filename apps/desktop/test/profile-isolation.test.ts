// Real Chromium heap strings, with the synthetic core held outside the renderer process.
import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vitest";

const root = path.resolve(import.meta.dirname, "../../..");
test("uia08_no_cross_profile_residue", async () => {
  const output = await mkdtemp(path.join(tmpdir(), "jana-profile-heap-"));
  for (const seeded of [false, true]) {
    const dir = path.join(output, seeded ? "seeded" : "clean");
    await promisify(execFile)(process.execPath, ["scripts/ci/browser-profile-isolation.mjs", dir, ...(seeded ? ["--retain-profile"] : [])], { cwd: root, timeout: 50000 });
    const result = JSON.parse(await readFile(path.join(dir, "result.json"), "utf8"));
    expect(result.before_present).toBe(true); expect(result.dom_leak).toBe(false);
    if (seeded) expect(result.after_string_count).toBeGreaterThan(0);
    else expect(result.after_string_count).toBe(0);
  }
}, 110000);
