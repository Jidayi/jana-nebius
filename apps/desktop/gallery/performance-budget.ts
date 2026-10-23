/** Budget checks for the development replay and future calibrated CI runs; missing observations never count as zero. */
export interface PerformanceSample {
  turns: number; board_steps: number; deltas: number; max_transcript_nodes: number; max_dom_nodes: number;
  frame_p50_ms: number | null; frame_p95_ms: number | null;
  input_p50_ms: number | null; input_p95_ms: number | null; input_samples: number;
  long_tasks_supported: boolean; max_long_task_ms: number | null;
}
const LIMITS = { max_dom_nodes: 3000, frame_p95_ms: 16.7, input_p50_ms: 50, input_p95_ms: 100, max_long_task_ms: 50 } as const;
export function performanceFailures(sample: PerformanceSample, baseline?: PerformanceSample): string[] {
  const failures: string[] = [];
  if (!Number.isInteger(sample.turns) || sample.turns < 500 || !Number.isInteger(sample.board_steps) || sample.board_steps < 30 || sample.deltas !== 5000) failures.push("Replay needs 500 turns, 30 board steps and exactly 5,000 deltas.");
  if (!sample.long_tasks_supported) failures.push("Long-task observation is unavailable.");
  if (!Number.isInteger(sample.input_samples) || sample.input_samples < 1) failures.push("No typing was measured.");
  for (const [name, limit] of Object.entries(LIMITS)) {
    const key = name as keyof typeof LIMITS, value = sample[key];
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) { failures.push(`${name}: missing or invalid observation.`); continue; }
    if (value > limit) failures.push(`${name}: ${value} exceeds ${limit}.`);
    const previous = baseline?.[key];
    if (typeof previous === "number" && previous > 0 && value > previous * 1.1) failures.push(`${name}: regression exceeds 10%.`);
  }
  return failures;
}
