# Jana feature import — 25 October 2026

Imported feature source and tests from the local `../jana` working tree, whose HEAD was `41b57e01`, into this fork. This is a source integration, with three-way merges against the fork's initial snapshot; it does not replace the fork or copy another repository's Git directory.

| Capability | Entry point |
| --- | --- |
| Tutor pen and annotations, pointing back, diagram manipulation and replay | Tutor board and supported diagrams |
| Rough sketches and additional biology, chemistry, physics and maths visuals | Tutor visuals; development gallery at `/gallery.html` |
| Weekly parent summary and local PDF printing | Settings → Parent summary |
| Local parent alerts | Settings → Alerts |
| Retained conversations, boards and visuals, read-only | Progress → Session history |
| Item and skill analytics, diagrams and authoring reports | Authoring Studio → Analytics and reports |

The browser development adapter uses stage S3 to expose these imported screens. This is a development feature setting, not a production release acceptance claim. Sketches retain their checked/unchecked status and their measured token cost is recorded separately.

## Preserved fork behavior

The Nebius gateway, NVIDIA runtime, existing inference budget, consent checks and profile data remain in place. The daily plan, lesson, practice, assessment and Study journey work is preserved, including saved quiz answers, citations and returning from tutor help. Private specification files, provider credentials, model weights and application data are excluded from this import.

Integration fixes include exported contract paths, generated visual/worker bindings, parent-report print tokens, local Greek font coverage, and sketch-cost assertions using this fork's provider price table. Mock follow-up practice now keeps every weak idea in its set rather than opening a new journey for only the first idea.

## Verification follow-up

Testing the integrated app exposed connections that the isolated source-feature tests did not cover. These were fixed:

- Completed visuals and sketches stay visible in the conversation instead of disappearing into the folded check summary.
- Annotations, sketches and pending diagram exercises survive snapshot hydration and reopening. Board replay works after a core restart.
- Supported checked diagram parts offer **Try on the diagram**. Number-line endpoints, graph coordinates and force magnitude/direction use the real maths worker and write the checked result onto the board. Failed requests retain the student's values for retry.
- Session history displays the saved board alongside the conversation and visuals, with editing and reporting controls disabled.
- Removing a sketch also removes its stored history part, including after a restart.
- A Studio lesson preview no longer overflows into the analytics panel.
- Punnett-square parts have real minimum-size click targets, including the ratio labels at enlarged text sizes.

## Validation

- Backend feature and journey integration suite: **178 passed**, covering parents, history, annotations, manipulation, replay, pointing, sketches, science visuals, analytics, learning journeys, Study and tutor handoff. The new round-trip regression restarts the core with a pending exercise, uses real sandboxed maths-worker checks for all three manipulation kinds, removes a sketch from stored history and checks profile isolation.
- Complete UI suite: **636 passed**; complete client suite: **361 passed**; renderer suite: **55 passed**; Studio suite: **34 passed**; maths/science worker suite: **102 passed**; i18n suite: **5 passed**.
- Desktop and Studio production builds and the client, UI, desktop and Studio type checks passed. Generated-contract consistency, changed-source ESLint, Python Ruff and whitespace checks passed.
- The complete desktop run finished with **263 of 266 tests passing initially**. Its two failing accessibility suites found only the Punnett targets described above: 4 failures among 1,484 standard-text cases and 8 among 2,968 enlarged-text cases. After the fix, all **16 affected theme/width/text-size combinations passed** with no accessibility, layout or console errors. The full click-target audit passed **5,936 cases**. The third failure was an outdated keyboard-runner assertion expecting the old direct practice endpoint; it now verifies the lesson's retained objective and the journey's targeted practice set, and **all four keyboard-only journeys pass**. The complete desktop suite was not rerun after these focused corrections.
- Browser checks used the actual desktop client, local API and sandboxed worker with a scripted tutor and disposable synthetic profiles. Verified wrong/correct number-line feedback, graph coordinates and force vectors; pending-exercise reload; visible diagrams, science visuals and rough sketch; sketch removal surviving reload; saved read-only boards; a populated 65-minute parent summary; alert dismissal retained on a fresh open; and separation between learner profiles.
- Studio browser checks used a separate temporary content workspace and authoring home. Verified statistics and confidence intervals over 269 synthetic evaluation students, queue resolution retained on refresh, and a content problem report opening the corresponding item draft. Normal project workspace hosting was restored afterwards.
- Evidence and logs: `/private/tmp/jana-feature-verification-20261025`. Synthetic test data was kept separate from the app's existing learner data. The normal app was restarted on port 5187 with its original data and local NVIDIA model; Studio remains on port 5191.

### Limits of this verification

The live NVIDIA Nemotron tutoring smoke test completed, but answered the diagram request in words. The low-hardware local decode policy deliberately omits model-generated visuals. Controlled end-to-end tests establish that the imported visual UI/API/storage paths work; they do not qualify every live model's diagram or sketch generation.

The parent-summary print action entered the print presentation, but the browser-control interface could not complete the system print dialog. An exported PDF has **not** been visually verified. Native voice playback and spoken-cue pen synchronisation were covered by automated tests rather than a live microphone/speaker test. Native supported-webview and screen-reader acceptance remain separate from Chromium browser checks.

## Demo notes check — 26 October 2026

- A synthetic hand-drawn maths image uploaded through Home → Upload in the real Study QA profile. Extraction returned `unreadable_source`; the local reader also reported low-confidence text for that sample. This is not a qualified handwriting recognizer, and there is no student freehand writing pad in the UI.
- Manage material → Correct or replace source text saved a manually reviewed transcription as revision 2, ready for Study. The unreadable-material notice now offers that correction directly.
- Restarted the stopped budgeted gateway with its existing ledger and restored the app in stable preview mode. A failed startup now reaches recovery instead of polling forever; a host that stays unavailable has a bounded wait.
- Checks: 132 notes/capture backend tests, 51 Study UI tests and 3 startup-recovery tests passed, along with desktop type checking and changed-source ESLint. Logs and the clearly labelled synthetic drawing are in `/private/tmp/jana-demo-verification-20261026`.

Automatic handwritten-note recognition and direct pen input remain gaps for a handwriting-focused demo. Uploading an image and correcting its transcription is the verified path.

### Photo/scan review follow-up

- The requested demo input is a photo or scan of handwritten notes. The configured Nemotron inference routes are text-only; no automatic handwriting-recognition claim is made.
- Original photos and PDF pages can now be opened even when extraction produced no passages. Opening text correction also loads the original for comparison, with an expanded layout on narrow screens.
- Text corrections retain access to the most recent original file at or before that revision. A later file replacement cannot change an older revision's preview. Unfinished uploads and deleted sources stay inaccessible.
- Live browser verification opened the original photo from the previously saved corrected revision, then saved an exact two-line transcription as revision 3. Study chat answered “The notes show x = 10.” with a citation to revision 3. Photo/PDF regression cases cover corrected revisions, later file replacements and deletion; 97 Study backend cases, 53 Study UI cases and 5 catalogue cases passed. Type checking, lint and the preview build passed.
- A further scanned-PDF upload was not verified in the browser: file-chooser automation stalled and the session expired before attachment. The scan did not appear in the library. Real sandboxed PDF raster tests passed; this does not count as a completed browser upload.

## Local checkpoints

The complete pre-import working tree was backed up under `/private/tmp/jana-feature-port-20261025` and checkpointed separately at `a69f50d7161a` on `codex/import-jana-features`. The feature import follows that checkpoint so its changes can be reviewed independently. No remote push is part of this operation.
