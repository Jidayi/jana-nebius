import { expect, test } from "vitest";
import { performanceFailures, type PerformanceSample } from "../gallery/performance-budget.js";
const sample: PerformanceSample = { turns: 500, board_steps: 30, deltas: 5000, max_transcript_nodes: 900, max_dom_nodes: 2500,
  frame_p50_ms: 8.3, frame_p95_ms: 16.6, input_p50_ms: 2, input_p95_ms: 10, input_samples: 50,
  long_tasks_supported: true, max_long_task_ms: 20 };
test("uia32_perf_regression_caught: a 10% regression fails even within the absolute budget", () => {
  expect(performanceFailures(sample, sample)).toEqual([]);
  expect(performanceFailures({ ...sample, input_p95_ms: 11.1 }, sample)).toContain("input_p95_ms: regression exceeds 10%.");
});
test.each([['max_dom_nodes', 3001], ['frame_p95_ms', 16.8], ['input_p50_ms', 51], ['input_p95_ms', 101], ['max_long_task_ms', 51]] as const)("the %s budget is enforced", (key, value) => {
  expect(performanceFailures({ ...sample, [key]: value }).some((failure) => failure.startsWith(key))).toBe(true);
});
test("unmeasured typing and unsupported long tasks cannot produce a passing observation", () => {
  expect(performanceFailures({ ...sample, input_samples: 0, input_p50_ms: null, input_p95_ms: null, long_tasks_supported: false, max_long_task_ms: null })).toHaveLength(5);
});
