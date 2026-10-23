import { test } from "node:test";
import assert from "node:assert/strict";
import { PROFILE, evidenceFailures, qualificationGaps, parseArgs } from "./performance-evidence.mjs";
const sample = { turns: 500, board_steps: 30, deltas: 5000, max_transcript_nodes: 900, max_dom_nodes: 2500, frame_p50_ms: 16, frame_p95_ms: 16.6, input_p50_ms: 20, input_p95_ms: 30, input_samples: 50, long_tasks_supported: true, max_long_task_ms: 20 };
const report = { profile: PROFILE, sample, source_sha256: "a".repeat(64), runner_sha256: "b".repeat(64), runner: { browser: "test", cpu: "test" }, console_errors: [], review: { reviewer: "Synthetic reviewer", evidence_sha256: "e".repeat(64) } };
test("bare self-test and qualification flags are enabled and paths preserve equals signs", () => {
  assert.deepEqual(parseArgs(["--self-test", "--require-qualified", "--out=/tmp/a=b"]), { "self-test": true, "require-qualified": true, out: "/tmp/a=b" });
});
test("a runner change cannot silently reuse a baseline", () => {
  assert.deepEqual(evidenceFailures(report, report), []);
  assert.match(evidenceFailures(report, { ...report, runner: { cpu: "other" } }).join(), /requalification/);
});
test("missing and invalid observations cannot establish a baseline", () => {
  assert.match(evidenceFailures(report, { ...report, sample: { ...sample, input_p95_ms: null } }).join(), /Baseline does not meet/);
  assert.match(evidenceFailures(report, { ...report, review: null }).join(), /Baseline needs its reviewer/);
  assert.match(evidenceFailures({ ...report, sample: { ...sample, input_samples: NaN, turns: NaN } }).join(), /Replay needs/);
});
test("relative regression fails within the absolute budget", () => {
  assert.match(evidenceFailures({ ...report, sample: { ...sample, input_p95_ms: 34 } }, report).join(), /regression exceeds 10%/);
});
test("software passes never invent calibration or device evidence", () => {
  assert.equal(qualificationGaps(report, null, null).length, 3);
  const calibration = { runner_sha256: report.runner_sha256, cpu_rate: 4, reference_device: "lab-low-1", reviewer: "lab-reviewer", evidence_sha256: "c".repeat(64) };
  assert.equal(qualificationGaps(report, report, calibration).length, 1);
  assert.equal(qualificationGaps(report, report, { ...calibration, runner_sha256: "d".repeat(64) }).length, 2);
});
