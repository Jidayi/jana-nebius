# Desktop client

The React client (D18) in `src/`, its dev-only component gallery in `gallery/`, and the Tauri shell in `src-tauri/`.

A question queued while the tutor starts belongs to the open student and is discarded on a profile switch or lock.
Learn keeps its menu and a Settings action when no subject content is installed.

Archive restoration is available from first run, the profile picker and profile-store recovery. The shell's
`pick_profile_archive` capability opens a `.janaprofile` picker; the client waits for the import job to finish before
offering the restored profile. Cancelling the picker leaves recovery open; failed imports can choose another file.

Diagnostics open from the first-run hand-off, Home and Progress. Mastery checks open from topic sheets and plan
activities. Both use the local assessment API and recover saved runs after restart; diagnostic screens show no marks.
An unanswered mastery item keeps tutor routes closed, matching the core's assessment guard, including after stopping.

Saved questions has its own sidebar place. The latest completed tutor reply offers Save for later; its immutable
snapshot can be searched, shown, printed, resolved or removed locally. The list clears with the profile.

Study notes separates generated session notes from notes the student writes or dictates. The tutor's More menu offers
End session and view notes. Every generated statement links to its accepted source turn in a history view, including
when no model is available. Private text stays out of lists and searches until the student confirms opening it.

## Run it in a browser (development)

```bash
cd apps/desktop && npx vite
```

The dev server starts the agent core as the shell would, over its control channel with a fresh launch token, with
the development model script. Open `http://localhost:5180/` for the tutor and `http://localhost:5180/gallery.html` for
the gallery. With a local llama-server, set `JANA_DEV_RUNTIME="<url> <key> <model>"` before starting the dev server.
Set `JANA_DEV_DATA_DIR` to an existing development data folder to keep its local profiles and sessions across restarts.

## Run it as the desktop app (development)

With the dev server running:

```bash
cargo run -p jana-shell
```

The shell starts and supervises its own agent core and hands the window the core's address and token through the
`launch_info` command.

## Tests

```bash
npx vitest run
```

```bash
cargo test -p jana-shell
```

Design contracts are in [DESIGN.md](DESIGN.md).

Long sessions use variable-height transcript windowing after 40 turns. Heights are keyed by row/part content, width and text scale. Streaming turns, open cards, reading anchors and focused rows remain mounted; search reads the store and mounts its hit. Earlier/Later controls provide keyboard navigation. Session-note history links use the same positioning path. Draft editing remains available while a tutor streams, with submission still guarded.

The development-only browser replay is at `/gallery.html?benchmark=transcript`. It creates 500 synthetic turns, a 30-step board and replays 5,000 deltas through the production queue/reducer while scrolling. Type in the actual Ask editor to collect key-event-to-next-frame observations. Its JSON includes frame quantiles, whole-page and transcript DOM counts, typing samples, long tasks and absolute-budget failures. The budget helper also rejects regressions over 10% against an explicitly supplied baseline. A missing observation cannot pass. These measurements do not establish input-to-paint timing on the reference laptop, 4× CI calibration, startup/RSS budgets or candidate acceptance.

Desktop and Studio load their application module after the shared launch screen. The learner validator entry (`@jana/contracts-ts/client`) is generated from the same canonical contracts, limited to API commands/events, student records and visuals; corpus parity is tested against the complete validator set. Application, editor, maths and validators build into separate local chunks.


The M42 **Study** workspace is an opt-in development preview. Launch development with
`JANA_STUDY_WORKSPACE_ENABLED=true`; the sidebar entry appears only when the core advertises `study_workspace`.
It is disabled by default and the override is ignored in release builds. See the M42 section of
[`services/agent-core/README.md`](../../services/agent-core/README.md) for formats, local-model requirements,
migration/rollback behavior and the remaining archive/cloud/OCR qualification gates.
