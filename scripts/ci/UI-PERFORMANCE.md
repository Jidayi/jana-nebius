# UI performance replay

With frozen workspace dependencies installed:

```sh
pnpm exec playwright install chromium
pnpm --filter @jana/desktop exec vite build --config benchmark.config.ts
node --test scripts/ci/performance-evidence.test.mjs
node scripts/ci/browser-performance.mjs --self-test --out=dist/ui-performance
```

The gallery CI stage runs this production-optimized synthetic entry, using the Chromium version pinned in
`pnpm-lock.yaml`, a 1366×768 viewport, reduced motion and 4× CPU throttling. It replays exactly 5,000 deltas into
500 stored turns, displays 30 board steps, scrolls at 1,200 px/s and types 50 real keystrokes during streaming.
Only the loopback static fixture server is accessible. No model or learner profile is opened. The second replay
adds an 80 ms blocking board render on each store revision and must fail the frame or long-task budget.

`replay.json`, `slow-board.json` and their screenshots are retained even when budgets fail. The artifact records
the source digest, commit, browser, CPU, viewport and measurement profile. Input latency is a conservative
keydown-to-second-animation-frame bound, including a paint opportunity; it is not photodiode/device-lab timing.
Frame cadence uses animation-frame timestamps. Timing runs must not overlap builds or test suites.

Compare a reviewed observation with:

```sh
node scripts/ci/browser-performance.mjs --baseline=/path/to/reviewed/replay.json --out=dist/ui-performance
```

Both absolute budgets and a 10% relative limit apply. Missing/invalid samples and incompatible hardware/browser
profiles fail. Do not replace the baseline automatically with the current result. CI uses
`scripts/governance/ui-performance-baseline.json` when a lab-reviewed baseline is supplied; otherwise it runs
absolute budgets and records the missing relative-acceptance evidence. A runner/browser change requires review.
The baseline must include `review.reviewer` and `review.evidence_sha256` from that review; a raw observation cannot
silently become an approved baseline. This metadata check does not independently establish the review's validity.

Calibration is supplied separately as `--calibration=/path/to/calibration.json` (CI path:
`scripts/governance/ui-performance-calibration.json`). The record must name the reference device, reviewer,
SHA-256 of the lab's evidence, the matching artifact `runner_sha256`, and `cpu_rate: 4`. The software checks the
binding; only the lab can establish calibration. It never creates or approves this record.

`--require-qualified` fails while any qualification evidence is missing. These synthetic reports always leave
reference-laptop maximum-model-rate input-to-paint, startup and two-hour webview RSS acceptance to the device
lab. They always say `candidate_acceptance: false` and `reference_hardware: false`. Passing this replay cannot
certify those measurements, native webviews or a release candidate.
