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

At this initial checkpoint, automatic handwritten-note recognition remained a gap. The later automatic-extraction
qualification below supersedes that limitation. Direct pen input remains separate from photo/scan importing.

### Photo/scan review follow-up

- The requested demo input is a photo or scan of handwritten notes. The configured Nemotron inference routes are text-only; no automatic handwriting-recognition claim is made.
- Original photos and PDF pages can now be opened even when extraction produced no passages. Opening text correction also loads the original for comparison, with an expanded layout on narrow screens.
- Text corrections retain access to the most recent original file at or before that revision. A later file replacement cannot change an older revision's preview. Unfinished uploads and deleted sources stay inaccessible.
- Live browser verification opened the original photo from the previously saved corrected revision, then saved an exact two-line transcription as revision 3. Study chat answered “The notes show x = 10.” with a citation to revision 3. Photo/PDF regression cases cover corrected revisions, later file replacements and deletion; 97 Study backend cases, 53 Study UI cases and 5 catalogue cases passed. Type checking, lint and the preview build passed.
- A further scanned-PDF upload was not verified in the browser: file-chooser automation stalled and the session expired before attachment. The scan did not appear in the library. Real sandboxed PDF raster tests passed; this does not count as a completed browser upload.

### Automatic handwriting extraction

- Study now uses a separate MiniCPM vision reader on the existing Nebius provider when printed OCR cannot read a photo or scanned PDF page. Nemotron still teaches and generates Study aids. Only sandboxed, privacy-screened JPEG derivatives reach the reader; credentials stay in the gateway.
- The shared deployment budget now supports one bounded image on a configured vision route, reserving its full input context. Remote image URLs, unsupported modalities, oversized images and multiple images are refused. Existing daily/total/expiry caps and the persistent ledger are unchanged. Per-page extraction receipts include actual vision usage; replays use the frozen result without another model call.
- Fixed a HOG false positive on the synthetic biology notes with a Study-only text corroboration check. Face/cascade hits still refuse; unexplained ink, missing OCR and ordinary capture photos do not receive the exception. OpenCV's public basketball people sample remained blocked.
- Live app API uploads automatically transcribed both the drawn maths photo and the two-page maths/biology scan, in page order. Both were saved as unreviewed extracted text, and an attempted generation without review was correctly refused. The bundled [demo PDF](evals/perception/handwriting/demo-scanned-notes.pdf) has no searchable text layer. These synthetic examples qualify the demo flow rather than all handwriting.
- Checks: 336 affected backend/privacy/budget/Study cases, 53 Study UI cases and 5 catalogue cases passed. Python/desktop type checks, lint and the production preview build passed. Evidence is under `/private/tmp/jana-demo-verification-20261026`.
- The real app displayed the original second scan page alongside its automatic transcript. After review, Study answered that enzymes are biological catalysts and that high heat changes the active site's shape, with a page-2 citation. This required no manually typed transcription.
- Browser upload is now verified through Home → Upload → Chrome's standard macOS file picker, selecting the bundled two-page `demo-scanned-notes.pdf`. Jana received all 96,800 bytes, completed automatic extraction of both pages, and displayed the original second page with its matching transcript. After checking the review confirmation, Study correctly answered what enzymes are and what high heat changes, with a page-2 citation to this newly uploaded PDF. No transcription was typed or corrected during this test. This supersedes the earlier unqualified browser-upload checkpoint.
- Chrome's extension-based `setFiles` helper continued reporting unavailable file-URL access after the user enabled it. The standard picker succeeded without depending on that permission, and the user was immediately told to turn the temporary permission off. This helper limitation is separate from the verified app upload path; the agent cannot verify or change Chrome's protected extension settings.

## Local checkpoints

The complete pre-import working tree was backed up under `/private/tmp/jana-feature-port-20261025` and checkpointed separately at `a69f50d7161a` on `codex/import-jana-features`. The feature import follows that checkpoint so its changes can be reviewed independently. No remote push is part of this operation.


## Alex Morgan Study demo — 27 October 2026

- Alex's in-app-browser upload attempts had not created any source record. The exact native picker failure is not established. File selection now survives until the asynchronous upload completes; bounded FileReader reads show a useful failure after 15 seconds, refuse short reads and prevent late reads from writing after a profile change. A source created before a chunk failure is reopened in the library for resumption.
- Added an explicit **Use example scanned notes** action with clearly labelled synthetic maths/biology content. It loads the existing two-page image-only fixture from the app's static assets and passes it through the normal file upload, privacy, consent and automatic transcription pipeline. It does not prepopulate profiles or substitute a typed transcript. Late example loads cannot start an upload after workspace departure.
- Live in-app-browser verification as Alex: example uploaded and both pages transcribed automatically; original page 2 matched its transcript; reviewed-source chat correctly answered the enzyme/heat question, and both citations opened page 2. All six Study tools generated and reopened: summary, three-question quiz, three flashcards, notes, podcast and lesson plan. The PDF, all six tools and review progress survived a fresh app load. The quiz saved three correct answers; rating all three cards left zero due today. Podcast narration advanced to passage 2 of 3 before being stopped; speaker output was not independently heard. The generated lesson plan is currently rendered as referenced learning statements, without a timed schedule.
- This qualifies the explicit example-file path in the in-app browser. It does **not** requalify that browser's native picker or establish recovery of the user's missing attachment. Standard Chrome native-picker upload was qualified at the preceding checkpoint. Browser extension file-URL permission remains off.
- Focused checks: 48 client Study tests, 62 UI Study/Home tests and 5 catalogue tests passed. Client/UI/desktop type checks, changed-source ESLint, whitespace checks and the production preview build passed.


### Real-file import handoff

- Home's Upload and Record now open Study's import panel before selecting any local file. This removes the hidden-input programmatic click and avoids unmounting Home's picker during an asynchronous read. Study presents a visible native picker, displays the selected filename/size, and waits for **Upload selected file** before sending bytes. Dropped files use the same confirmation step. No example material is selected automatically.
- StrictMode desktop regression tests cover both Home entry points, the retained native input and the exact selected File reaching the upload controller only after confirmation. Focused checks passed: 63 Study/Home UI cases, 4 desktop routing cases and 5 catalogue cases; desktop type checking, changed-source ESLint and the production build also passed.
- Official browser documentation states that ChatGPT cannot automate file uploads in the built-in browser: https://learn.chatgpt.com/docs/browser#computer-use-in-the-browser . The user must operate the native picker for live qualification. This explains why the automated attachment helper is not a valid acceptance test; it does not establish the cause of the user's previous manual-upload report. The actual personal-file upload remains pending user selection, and no success is claimed for it at this checkpoint.


### Remove the unsaved-selection chat handoff

- Subsequent checks found the app signed out with no selected file available to submit. Leaving a file selected and waiting for an agent was not a reliable upload handoff: that selection had not been saved and normal profile clearing discards it.
- File selection and dropping now immediately start the normal upload/extraction pipeline inside the already mounted Study workspace. The native picker is labelled **Choose a file to upload**, and the screen explains that upload starts on selection. The extra confirmation button has been removed. Home still navigates into Study before any file selection; it never starts a read while unmounting its own input.
- Native form changes count as learner activity alongside keys/pointer/wheel; authentication, idle-lock duration and profile-clearing behavior are unchanged. Regression cases verify immediate delegation of the exact selected file for both Home entry points, with file-change activity recorded and the input held until reading/upload completes.
- Validation: 63 Study/Home UI tests, 4 desktop routing tests and 5 catalogue tests passed, as did desktop type checking, changed-source ESLint, whitespace checks and the production preview build. The selected personal file had already been cleared; its real upload/transcription remains unverified until the user selects it in the new immediate-upload flow. No example file was uploaded during this follow-up.

### Restore the unavailable demo host — 28 October 2026

- The browser retained its app UI while both local services were stopped. After restarting the budgeted gateway, app startup still failed because the host's saved credential ID referred to a different public key. Both subscription device slots were occupied. This is a confirmed current availability failure; it does not establish what happened in earlier native-picker attempts.
- Retired only this host's active, orphaned binding after checking its account, licence and expiry. Restarting registered the current host key under the same account and limits. The other device, learner databases, spending caps and usage ledger were retained. No automatic revocation or device-limit bypass was added.
- The development launcher now migrates its existing key store into an ignored, owner-only `.local-state/dev-keys/` directory, keyed by the demo data path. Existing destination keys are retained. Startup refuses an ID without its private key instead of silently generating a replacement. Safe startup logs report credential refusal states without secrets.
- Verification: 11 host tests passed, including migration, permissions, preserving existing keys and repeated refusal of a missing private key. Ruff, source-aware Python type checks and whitespace checks passed. Live gateway health returned 204 with budget enforcement enabled; the app launch endpoint returned 200. Alex Morgan's existing profile and library opened successfully in the in-app browser.
- Alex's library still contained only the example scan. A local `Downloads/notes.pdf` candidate is a 69-page printed machine-learning document, not a handwritten scan; copies with the same file hash belong to older uploads under other test profiles. No cross-profile transfer was made. Confirmation of the candidate file and a fresh personal-file upload/transcription check remain pending; native in-app-browser upload is not newly qualified by this host repair.
