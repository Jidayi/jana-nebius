import { performanceFailures } from "../../apps/desktop/gallery/performance-budget.ts";

export const PROFILE = { fixture: "transcript-v1", cpu_rate: 4, viewport: { width: 1366, height: 768 }, input_metric: "keydown-to-second-animation-frame" };
export function parseArgs(argv) {
  return Object.fromEntries(argv.map((arg) => {
    const at = arg.indexOf("=");
    return at < 0 ? [arg.replace(/^--/, ""), true] : [arg.slice(0, at).replace(/^--/, ""), arg.slice(at + 1)];
  }));
}
export function evidenceFailures(report, baseline) {
  const failures = performanceFailures(report.sample);
  if (report.sample.input_samples < 20) failures.push("At least 20 keystrokes must be measured.");
  if (JSON.stringify(report.profile) !== JSON.stringify(PROFILE)) failures.push("Unexpected replay profile.");
  if (!/^[a-f0-9]{64}$/.test(report.source_sha256 ?? "")) failures.push("Missing source digest.");
  if (report.console_errors?.length) failures.push("Browser errors occurred.");
  if (baseline) {
    if (JSON.stringify(report.profile) !== JSON.stringify(baseline.profile) || JSON.stringify(report.runner) !== JSON.stringify(baseline.runner)) failures.push("Baseline browser, hardware or profile differs; requalification is required.");
    if (evidenceFailures(baseline).length) failures.push("Baseline does not meet the evidence and absolute-budget checks.");
    if (!baseline.review?.reviewer || !/^[a-f0-9]{64}$/.test(baseline.review?.evidence_sha256 ?? "")) failures.push("Baseline needs its reviewer's name and review-evidence digest.");
    failures.push(...performanceFailures(report.sample, baseline.sample));
  }
  return [...new Set(failures)];
}

// An observation can pass development checks without being a release qualification.
// This never creates, signs or approves calibration evidence.
export function qualificationGaps(report, baseline, calibration) {
  const gaps = [];
  if (!baseline) gaps.push("Reviewed baseline required for relative regression acceptance.");
  if (!calibration || calibration.runner_sha256 !== report.runner_sha256 || !/^[a-f0-9]{64}$/.test(calibration.evidence_sha256 ?? "") || !calibration.reference_device || !calibration.reviewer || calibration.cpu_rate !== PROFILE.cpu_rate) gaps.push("Device-lab calibration against the low reference laptop required.");
  gaps.push("Reference-laptop maximum-model-rate, startup and two-hour RSS evidence required.");
  return gaps;
}
