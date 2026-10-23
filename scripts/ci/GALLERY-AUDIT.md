# Browser gallery checks

After the benchmark build described in `UI-PERFORMANCE.md`:

```sh
node --test scripts/ci/visual-diff.test.mjs scripts/ci/colour-vision.test.mjs
node scripts/ci/browser-accessibility.mjs --self-test --out=dist/gallery-audit
node scripts/ci/colour-vision-report.mjs --out=dist/gallery-audit/colour-vision.json
```

The default matrix runs every fixture at 1366×768 and 800×768, light and dark, 100% and 150% body/maths text,
with reduced motion and bundled fonts. It checks WCAG 2.2 AA axe rules, overflow, clipped controls, actual computed
text sizes and 24 px targets. Small diagram geometry has an equivalent full-size part selector, including neutral
numbered options while labels are hidden. The audit verifies that this equivalent control exists before applying
the WCAG 2.5.8 exception. Label targets and their controls are both considered when measuring hit areas.

`--components=Practice,VoiceBar`, `--limit=2`, `--themes=dark`, `--scales=1.5` and `--widths=800` select development
subsets; `--states=fixture.id,other.id` selects exact fixtures. These do not establish full gallery coverage. Four pages run concurrently. Do not overlap a performance
timing run with this audit. A partial checkpoint is saved every 25 cases; the final `audit.json` records all cases,
violations and measured layouts. Any violation, clipping, target/scale error or console warning/error fails.

Screenshots are generated for review, never automatically approved. Compare a reviewed directory with:

```sh
node scripts/ci/browser-accessibility.mjs --baseline-dir=/path/to/reviewed/screenshots --require-baseline
```

Missing baselines fail in this mode. Pixel changes over 0.1% (pixelmatch perceptual threshold 0.1) produce `.diff.png`
files and fail until reviewed. Dimension changes also fail. CI uses `scripts/governance/ui-visual-baseline` when
provided, otherwise retains the unreviewed matrix. Existing renderer HTML goldens remain a separate check; their
updates are reviewable source changes, not screenshot approval.
`--self-test` changes the fixture's paper token and checks that its screenshot differs while the control outside
that fixture stays unchanged; its diff and result are retained in the audit artifact.

The colour-vision report evaluates all 28 semantic/chart role pairs in three Machado severity-1 simulations and
both themes (168 comparisons), using linear sRGB and CIEDE2000. Canonical contract version 0.6.0 gives the four chart
series independent colours and revises the semantic inks. All 168 CVD comparisons and 288 colour/surface contrast
checks pass. The applied values and specification commit are recorded in
`scripts/governance/app-completion-palette-proposal.json`; the SVG retains the before/after comparison.
The strict command remains mandatory. `--report-only` can collect observations but cannot establish LOC-19
acceptance. Changes must be made in the canonical contract and regenerated, never patched into generated output.

External acceptance remains separate: supported native webviews, NVDA/VoiceOver, complete keyboard journeys,
OS zoom/text settings, specialist manual audit, consented usability work and approval of visual differences. This
Chromium audit records `candidate_acceptance: false`; it cannot replace those observations.
