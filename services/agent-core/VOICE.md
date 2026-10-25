# Conversational voice implementation record

Updated 2026-10-15. Student voice extension integrated from `codex/m31-student-voice` (`31e02ca2`)
onto main's reconciled M21/voice base `17086d68`. The prior `codex/m31-read-aloud-dictation` follow-up is based on the stable voice foundation commit
`738e9669` on `codex/m31-voice-foundations` (original baseline `49871a47`). This follow-up has a separate worktree
so M21 can merge the foundation without concurrent edits to its snapshot.
M31/M32 and the M25 → M31 → M32 release dependency remain open. This record is not milestone acceptance.

## Cloud voice (VOC-28, S4)

Built ahead of its stage behind the engineering capability `cloud_voice_enabled` (default off), as Study was. With
it on, the `cloud_voice` switch and consent scope exist; a voice start goes online only when the switch is on, the
open profile holds an active `cloud_voice` consent, a subscription covers it, its first-use notice was accepted and
the network is usable. Otherwise the local sidecar serves the start, exactly as before.

- **Same bridge, same socket.** `net/voice_cloud.py` gives the unchanged `VoiceBridge` a `RealtimeConnection` to our
  hosted endpoint (`wss://<voice host>/v1/voice/realtime`). `VoiceRuntime.route` picks the endpoint at each voice
  start; the UI cannot tell the paths apart. A cloud connection that cannot open falls back to the sidecar when a
  pack is installed.
- **Mid-session fallback (VOC-29).** When the cloud connection closes, errors or misses three heartbeats (1 s pings,
  3 s timeout), the runtime interrupts the active response at the played position (heard text, VOC-36), opens the
  local sidecar through `VoiceRoute.fallback`, and the bridge replays the same binding's `session.update` on its
  `session.created`, then sends the microphone audio held meanwhile (memory only, at most 10 s). The student gets
  the contract `notice` `voice.now_local` ("Voice is now on this computer."). Without a pack voice ends as before.
  It returns online only at the next voice start. Not covered: a student utterance whose transcript was still being
  worked out on the gateway when the link dropped is discarded, not carried over.
- **Learner data stays here.** The hosted endpoint's language-model slot is tunnelled back on the same connection
  (`jana.voice_llm.request` / `.chunk` / `.done` / `.cancel`) and answered in process by the engine adapter
  (`voice_adapter.reply`), so the whole tutor turn and every gate run on the device. Only audio, the student's
  transcript and the accepted spoken words cross. Tunnel frames never reach the bridge.
- **Egress.** The connection is admitted by the connectivity layer (feature `cloud_voice`, payload `voice_stream`,
  credential, notice), ledgered, and announced as `egress.notice started` (`audio`, `transcript`) on the session
  stream before the socket is dialled; `ended` follows the close. TLS pins are checked in `connection_made`, before
  the upgrade request carrying the token is written. The token comes through `cloud_voice` at the voice host, so voice
  works with the cloud tutor switched off; the gateway accepts the voice host as a second token audience.
- **First use.** The engine asks once per profile with a confirm card ("Use online voice?" · OK / "Keep voice on this
  computer", key `egress.first_use.keep_voice_local`), one egress card at a time after the cloud tutor's.
- **Gateway, Google pipeline (D124)** (`cloud_gateway/voice.py`, off unless `voice_enabled`, refused with 4503 unless
  `voice_google.project` names the speech project):
  - *Hearing*: Cloud Speech-to-Text v2 streaming recognition (`chirp_3`, location `eu`, locale `en-GB`: Google
    offers no `en-NG`). Its `SPEECH_ACTIVITY_BEGIN`/`END` events become `speech_started`/`speech_stopped`, barge-in
    included; final results become append-only transcription deltas and the `completed` transcript. The recognizer's
    end of speech (500 ms) is held for the rest of the session's `silence_duration_ms`, so hold-to-think keeps one
    utterance. Streams are rotated at a quiet moment before Google's 5-minute limit.
  - *Thinking*: unchanged; the tunnel above. `response.created` still follows the device's first accepted words.
  - *Voice*: a Gemini Live session on Vertex AI (`gemini-live-2.5-flash-native-audio`, europe-west4, voice Kore, `providers/gemini_live.py`) set up with a fixed
    read-exactly instruction, output transcription, no activity detection and no session resumption. It is given
    only accepted sentences, one `clientContent` turn each, never audio. The gateway compares its output
    transcription with the sentence on letters and digits (case folded); a departure cuts its audio before the next
    chunk is forwarded and Cloud Text-to-Speech streaming (Chirp 3 HD, `en-GB-Chirp3-HD-Kore`) reads the rest of the
    turn from the first word not read exactly. Two departures switch the connection to Text-to-Speech only. Barge-in
    or Stop cancels Live's turn (the session is dropped and a fresh one prewarmed); the device truncates heard text
    at the played position. Transcript deltas follow the audio they belong to and always concatenate to the accepted
    words, so the bridge's `spoken_transcript_mismatch` check and heard text work unchanged.
  - *Latency*: the recognition stream and the Live session open with the connection, and `session.created` (which
    opens the device's microphone) waits up to `voice_prewarm_s` for them; audio arriving while a stream opens,
    rotates or resumes is held (up to `voice_first_words_ms`) and sent first. An adaptive idle timeout (twice the
    longest quiet stretch before the student spoke, 60 to 300 s, suspended while a turn runs) releases both
    sessions; a sound reopens them with its 500 ms pre-roll. `response.done` carries `vad_decision_s`, `hold_s`,
    `stt_s`, `llm_s`, `tts_ttfa_s`, `e2e_s` (estimated speech end to first audio) plus gateway extras `voice_out` and
    `prewarm_s`, never text.
  - *Zero retention*: audio is held only while it waits for a stream and overwritten when released; transcripts and
    spoken text live only while their utterance or reply runs; the ledger records feature `cloud_voice`, model,
    seconds or characters as cost, latency and status. Ids, locales, voices and prices are `voice_google` in
    `defaults.toml`, with their sources (checked 2026-10-21). The gRPC clients are the gateway's `google-voice` extra.
- **Tests.** `services/cloud-gateway/tests/test_gateway_voc28_cloud_voice.py` runs the real gateway against fakes of the
  three services (`cloud_gateway/speech_fakes.py`): `voc28_live_reads_only_accepted_text`, departure cut and
  Text-to-Speech finish, two departures, barge-in and truncation, prewarm, buffered first words, idle release and
  resume, hold-to-think, `voc28_endpoint_zero_retention`, recognition failure, wire subset, auth and the checker.
  `services/agent-core/tests/test_voc28_cloud_voice.py` is the end-to-end turn from the UI socket through the real
  bridge, engine and gateway over pinned TLS (`voc28_egress_announced`, `voc28_off_means_local`,
  `voc29_fallback_to_local`). `test_voc28_live_google.py` is the opt-in live smoke test (`JANA_LIVE_GEMINI=1` for
  Live; `JANA_LIVE_GOOGLE_VOICE=1` with `JANA_VOICE_PROJECT` for Speech-to-Text and Text-to-Speech).
- **Live run (2026-10-21, jana-staging-512005):** Cloud Text-to-Speech then Speech-to-Text v2 streaming round trip
  passes with `begin`/`end`/`final` voice-activity events; Live on Vertex (`gemini-live-2.5-flash-native-audio`,
  chosen by the owner because Vertex does not serve `gemini-3.8-live`) read the test sentence exactly in 3 of 3 runs,
  first audio about 0.69 s; Cloud TTS first audio 1.26 s warm, 3.4 s cold.
- **Open:** Live's transcription renders numbers its own way, so a sentence with digits may count as a departure;
  the client's rendering of the `voice.now_local` notice; the tunnel frames are not yet in the spec's Realtime
  contract; DPIA `s4_voice` before release.

## Student voice extension

Branch `codex/m31-student-voice`, based on the completed follow-up plus committed M21 (`374435a4`),
combined locally in integration commit `4d1a2034`. This worktree does not change the shared main checkout.

- Read-aloud now resolves versioned lesson blocks, individual lesson questions, accepted tutor question/hint cards
  and saved study notes. The core extracts only fields the student renderer shows, omits faded worked-example steps,
  refuses stale lesson versions and never reads keys or arbitrary client prose. Pack/note captions name the owned
  utterance without inventing a tutor turn. Existing Stop/restart, captions and OS/sidecar delivery are shared.
- The `read_aloud` preference queues newly accepted tutor text once. Streaming/rejected text and loaded history are
  skipped; another accepted message waits for playback to finish. Already-spoken conversational replies are skipped.
  Stop, navigation, preference disable and profile close clear pending playback. Low power disables automatic
  speech/conversation while preserving on-demand reading and dictation.
- Home Ask uses M21's rich editor and normal confirmed-capture Send path, with the same hold-to-dictate control and
  Ctrl+M. It submits only after explicit Send. Notes use a dedicated session socket, editable transcripts with
  uncertain recognition underlined, and explicit Save; they never submit a tutor question or enter `captures`.
- Study notes are local profile text in `study_notes`, searchable and deletable from the Notes screen, included in
  sealed profile archives and restored by import. No audio is stored. Migration 4 preserves M21 captures and drafts
  and existing preferences. This adds student-authored notes; automatic STU-14 session-note generation remains separate.
- Settings → Voice stores profile-local installed English OS voice choice and a 0.75–1.5 speech rate. PCM playback
  rate changes preserve source-audio played time for captions/heard-text reconciliation. The installed speech pack
  retains its packaged preset; runtime pack-speaker selection is not added. Reading/dictation state is announced,
  keyboard release survives focus movement, and deferred platform subscriptions avoid StrictMode listener leaks.
  Automatic OS screen-reader detection/ducking is still a platform acceptance item.
- D87 is enforced: microphone permission is exclusively the OS prompt at every age; the earlier app voice-consent
  gate is removed. Mock and profile isolation checks remain. Permission/cancel/profile-switch cleanup is covered by
  the shared lifecycle tests; real devices and real speech models remain release gates.
- Canonical activity, caption, preference and storage contracts are pinned to private revision
  `6917e76021ef41a61a73c0d8fec789c2b95656e7` (`codex/m31-student-voice-contracts`) in the source branch.
  Integration pins combined revision `361d81f5e083a9618cff8c3c31202b02e1e17589`, published to private
  `codex/m31-student-integration` before public integration. Bindings and contract fixtures were regenerated together.

Student extension verification: the combined core voice/profile/settings/export/M21 storage run passed **769 tests**
(one independent native photo sandbox smoke test deselected after its worker proved unavailable in this environment).
After adding disk-failure recovery, all **9 student voice tests** passed again, including retry after a failed note
save. Client voice tests: **24 passed**; shared UI tests: **34 passed**; desktop OS/audio/profile/lesson tests:
**20 passed**. Strict mypy passed for eight changed sources; Ruff, TypeScript, ESLint, six applicable architecture
contracts, codegen drift check and the production Vite build passed. No real audio device/model result is claimed.

## Read-aloud and dictation follow-up

- Completed tutor text parts offer Read aloud, Restart reading and Stop reading. The core resolves the part from
  the owning session, requires a completed text part and ended tutor message, and verbalises it. Requests accept
  references, never arbitrary client text or a candidate. Unused utterances expire after 60 seconds and are single-use.
- With a pack, the existing socket sends an engine-owned `jana-speak: utt_…` directive; the authenticated adapter
  returns the stored text verbatim, with no model, tutor turn, learning write or transcript mutation. Without an
  active pack socket, read-aloud uses an installed English OS voice whose `localService` flag is true. Network/default
  voices are refused. Actual OS word boundaries drive captions/highlighting; unavailable boundaries use a conservative
  syllable fallback. Sidecar captions use a playback-driven syllable estimate aligned to received audio.
- A scoped `stop` with `utterance_id` stops only that active or queued read. Stopping a read queued behind a tutor
  response leaves that response and its audio intact. Bare voice Stop retains tutor interruption semantics. Audible
  read restarts reset the speech unit to reject output from the old generation. Escape and navigation clean up playback.
- The composer has a separate hold-to-dictate control and Ctrl+M. D87 permits local microphone use for every age band with only
  the operating system permission prompt; no obsolete app consent table is queried. A live tutor turn or mock sitting refuses dictation. PCM uses the existing
  audio path. Dictation waits for key release, preserves completed segments across pauses and restores the fresh
  binding's instructions even when release and completion share one batch. Dictation adapter requests return empty
  streams; unexpected endpoint audio is dropped.
- Recognition creates a volatile `source: voice`, `awaiting_confirmation` capture. A deterministic English grammar
  handles the supported expression subset (powers, simple numbers/operators/fractions, scoped roots and chemical
  symbols); unsupported maths remains editable and uncertain spans are underlined. This is not a claim of passing
  the frozen 300-utterance accuracy gate. Recognized text is inserted as safe editor nodes without replacing an
  existing draft. Nothing is sent automatically. Send confirms the edited capture through the core, then submits
  it through M21's ordinary `capture_id` turn path. Confirmation alone starts no tutor turn. Failed confirmation keeps the draft.
- If M21's capture repository is attached, explicit confirmation promotes the record into its existing `captures`
  table, so M21's `capture_id` submission path can consume it. Unconfirmed drafts never enter that table. The schema
  handoff is tested against the real M21 v3 SQLite schema, foreign keys and HTTP capture/turn routes.
  Confirmation alone starts no turn; Send ignores replacement client text and uses the stored edited transcript.
  Voice input keeps student-text provenance; camera input keeps OCR provenance.
- Dictation keeps its old binding empty-only for delayed/speculative adapter requests, then rotates to a fresh tutor
  binding after terminal output. The desktop closes the completed dictation unit before a later talk request reopens
  the same session socket, keeping delayed empty responses out of the next generation. Stop, permission refusal,
  delayed grants/results, profile/session switches, typed-turn
  takeover and shutdown clean up capture work without creating a tutor turn. Drafts expire after ten minutes.
- The student extension above adds lesson/question/note sources, explicit Home Send, explicit note Save and
  preference-driven reading queues. Automatic STU-14 generated session notes remain separate.

## Goal progress

1. **Provisional isolation implemented.** `engine/voice_turn.py` forks the existing tutor engine, state, event stream,
   tool cache and spill storage. It buffers learner writes, saved questions, memory requests and cloud-notice writes.
   Discard cancels model work and leaves the live transcript, board, event log, checkpoint and learner records alone.
   Accepted effects land at first audio; the terminal event waits for playback completion or interruption.
2. **Authenticated adapter implemented.** `api/voice_adapter.py` exposes the sidecar's chat-completions LLM slot with
   its own token. Epoch/session capabilities select the tutor context; sidecar history and prompt prose are ignored.
   The normal guard, Coach, tool rounds, claim/leak checks and output critic still run. Only accepted spoken text is
   streamed. Tools are refused, warmup performs no turn, long turns send SSE keepalives, stale work expires, and
   engine failure has a fixed playable reply. Voice Coach reasoning is off; other roles use the existing lower budget.
   Accepted text is authorized before the upstream response id exists, avoiding a dependency cycle: the upstream
   creates that id only after the adapter returns text. Stop and hold-to-think revoke this pending authorization.
   Transport loss before release discards private work and carries recognized input into a normal guarded text turn.
3. **Interruption reconciliation implemented.** Stop, API cancel, spoken barge-in, session/profile close and shutdown
   flush playback and cancel/discard the matching turn. Accepted board operations remain. Checkpoints and transcript
   SQLite parts retain spoken text, heard text, played milliseconds and interrupted status. Profile lock finalizes
   these before closing its database. Partial heard text uses a conservative syllable estimate until word timings
   are available; full playback retains the exact spoken text. The next turn receives a one-shot interruption hint.
4. **Desktop and launch path implemented; real bundle validation pending.** `net/voice_launch.py` requests the shell
   to start a verified optional pack on first use, or early in the background while the open profile has read-aloud
   on (D96; stopped again if turned off before anything used it). `src-tauri/src/voice.rs` checks the entry-point hash, sends
   launch configuration/tokens on stdin, applies the 2-second / 2-crashes-in-300-seconds policy and closes the child
   with its owner. Readiness comes from the launcher's authenticated `session.created` probe. Core socket acceptance
   waits for readiness and the probe's pipeline reset; short unit-drain races are retried. Microphone traffic cannot
   accumulate while models load. `VoiceBar.tsx`, `voice-audio.ts`
   and the capture worklet provide localized PTT/hands-free/hold-to-think/Stop controls, OS microphone permission,
   PCM24k capture in 20 ms frames, playback and queue flushing. macOS microphone usage text/audio entitlement and
   loopback WebSocket CSP permission are included. Conversation is offered on mid/high only when a signed compatible
   English pack is found. The current loader supports Qwen3 preset speech; native CPU Kokoro and Pocket loaders
   deliberately fail closed until their local-file/G2P compatibility is established.
5. **Software verification implemented; device release gates pending.** Tests cover real tutor evaluation behind
   the actual ASGI adapter/socket, SQLite persistence, authenticated loopback transport, pack installation without
   networking, launcher authentication/egress controls, native fake-bundle supervision and synthetic browser audio.
   The pinned upstream's actual router, session service and resampler also run against the real core socket,
   authenticated adapter and tutor engine, with deterministic substitutes for STT/TTS workers.
   Real speech models, reference laptops and frozen speech sets have not been exercised.

## Components and protocol

- `engine/verbaliser.py`: deterministic English speech rendering, bounded input/depth, reason-only fallback codes.
  More than 500 distinct convention examples and 250 generated property examples cover the supported subset.
- `engine/voice_bindings.py`, `voice_bridge.py`, `api/voice.py`: single bound pipeline, strict/debug schema checks,
  stale-frame rejection, bounded PCM, independent generation/playback completion and sequenced voice states/captions.
  PTT release supplies 400 ms of digital silence in bounded frames. Explicit PTT can interrupt without echo
  cancellation; automatic spoken barge-in requires echo cancellation or headphones. Hold-to-think extends silence
  detection and discards an unreleased response so its words can be carried forward.
- `net/voice.py`: literal loopback WebSockets only, separate bearer header, no proxies, compression, query tokens or
  credential-bearing diagnostics. `websockets>=15,<16` is the only new core dependency; the lock selects 15.0.1.
- Binary output starts with 16 bytes of SHA-256(response_id). The UI reports playback using that hexadecimal tag;
  the bridge accepts the current raw response id or its tag. Flush frames name the raw id and the UI derives its tag.
- `store/speech_packs.py`: signed per-language manifest distinct from tutor model packs and their 7B floor. Every
  component has a role, selected hardware classes, source, SPDX licence, attribution, size and SHA-256. Install
  verifies in staging and atomically renames; loads recheck installed bytes. Extra files, symlinks, unsafe paths,
  excluded components, unknown licences, stale pins, incompatible platform/app/class and test roots in production
  are refused. Hashing uses bounded reads. Class installation copies only that class's components.
- `net/voice_sidecar.py`: separate-process entry point, local argument dataclasses, one unit, private Realtime auth,
  no HTTP/WebRTC/usage/pool/proxy routes, fixed LLM adapter configuration, local Silero and NLTK resources, no voice
  cloning, transcript/native log suppression, and a process-wide loopback-only socket/DNS audit hook. Both offline
  flags and the socket hook apply before speech libraries load. Upstream must be inside the verified bundle.
- `scripts/packaging/voice-upstream.json` pins speech-to-speech to
  `619e3fe4f71d1c6f35c15870d588a3638de34722`; source hashes and compatibility adaptations are recorded there.
  `voice-sidecar.spec` is the separate one-dir bundle recipe. It has not produced a release bundle in this run.
  `JANA_SPEECH_SOURCE` makes the compatibility tests inspect a pristine local checkout without loading models.
- The private specification checkout in this worktree contains the new speech-pack schema and voice launch/endpoint
  control frames. Bindings were regenerated from those sources, not edited by hand. The private source changes
  were committed on `codex/m31-voice-contracts` at `8fb6092a66346c0cd55e20ba4c96371acd007c7e`.
  The activities contract and scoped read Stop build on it on `codex/m31-read-aloud-dictation-contracts` at
  `18e44bace4ca7e9bdd0c6cb943609c547555a922`. Both revisions were reconciled with the latest M21
  contracts in `c8699bcf6b5a27f8f0c700f2f8dc7a719918dd3c`, published to the private
  `codex/m21-m31-read-aloud-integration` branch before this public integration. `spec.lock` pins that combined revision.

## Verification and limits

The Python suite includes verbaliser, reducer, socket/security, provisional-turn, adapter, actual SQLite delivery,
loopback WebSocket, signed pack, launcher and source-compatibility tests. New native code and the existing shell
supervisor compile and pass tests in a small harness using the real source files, without linking the Tauri host.
The fake bundle checks stdin-only credentials, bounded control replies, shutdown and crash give-up. It is not a
speech model. Client tests check socket generations, permission races, playback tags and resource cleanup. Desktop
synthetic audio tests cover input rates 16/24/44.1/48/96 kHz, mono PCM conversion and played-sample accounting across
buffering gaps. The desktop typecheck and production Vite build pass; the worklet is a same-origin `.js` asset,
explicitly excluded from asset inlining so it works with the app's CSP.

Final combined voice Python run: **719 passed** (including five actual-upstream protocol/integration cases).
The end-to-end test verifies no tutor commit before audio, then accepted output and exact spoken/heard text after
all resampler output, including its short tail frame, is reported played. Existing gate/auth/cancel regressions:
**14 passed** in the foundation run. Follow-up client voice/activity tests: **18 passed**; desktop OS/audio/profile/lesson
tests: **16 passed**; UI composer/transcript/activity tests: **22 passed**. Foundation native source harness:
**6 passed**. Changed Python files pass Ruff; six changed lifecycle/activity/adapter/store files pass strict mypy.
Contract regeneration check, five applicable architecture contracts and desktop/client typechecks pass.

Voice traces contain source/path/mode, discard/carry status, interruption cause and heard milliseconds, plus measured
adapter-first-sentence and release offsets. They contain no audio or transcript. STT/TTS/e2e/playback-start timings
are omitted until actually available; no synthetic measurement is presented as a device latency result.

Remaining before release:

- Build a fully inventoried, licence-reviewed speech environment and signed real pack with all local models and NLTK
  resources; the repository's existing build-tool hash placeholders still prevent a release PyInstaller build.
- Exercise the model-backed pinned pipeline and every selected runtime on supported operating systems, including packaged
  imports, cold/warm startup, worker teardown and Windows process-tree cleanup. The native harness is not a full
  Tauri integration or platform signing test.
- Run real microphone → STT → gated tutor → TTS → speaker journeys, packet capture with external networking disabled,
  peak memory with the tutor model resident, latency/cancellation budgets, noisy/paused dialogues, accent/vocabulary
  WER and listener intelligibility on frozen licensed/consented adult datasets and reference devices.
- Broaden the spoken-maths grammar against the frozen 300-utterance corpus. Finish accurate caption word timing/pointing,
  screen-reader detection/ducking, speech-pack speaker selection and broader M32 scenario/typed-steering UX.
  Home Ask, student notes, lesson/question reading, automatic reading queues and voice/rate settings are implemented above.
- Reconcile and publish the pinned private contract changes before integration with the other implementation
  branches. M25/M31/M32 acceptance is not claimed by any passing synthetic test above.

## Integration with M21 on main (2026-10-15)

M21 input/capture was committed first (`d13a2838`), after the profile/storage/pack prerequisites (`ff3ee64d`).
The voice merge pins combined private contracts at `c7973fa`: capture/update and voice control definitions coexist,
and camera plus microphone permissions are retained. Profile middleware keeps schema-derived HTTP guards and validates
voice subprotocol credentials on `/v1/sessions/{id}/voice`; capture cleanup and voice delivery finalization both run
before profile storage closes. Generated bindings and contract fixtures were rebuilt from the combined pin.

Clean integration testing also identified M21's required worker grammar support for its converter shortcuts
(`cbrt`, `root`, `frac`, relational commands and parenthesized subscripts). Those previously uncommitted changes are
included as an integration prerequisite. Other curriculum, marking and review changes remain outside this merge.
The WebSocket dependency now has its pinned distribution review and third-party notice; voice controls use existing
design font tokens and discoverable localized state labels.

Final combined voice/M21/profile verification: **732 Python tests passed**, including the actual pinned upstream
protocol tests with synthetic audio/events. Client core: **107 passed**; shared UI: **104 passed**; desktop: **37 passed**.
The real native crate compiles; its voice supervisor tests: **4 passed**. TypeScript checks, desktop production build,
Ruff, strict mypy, code generation, contract fixtures, architecture and dependency/licence/notice checks passed.
The prior broader HTTP API run passed its 40 cases; its three voice authentication failures were corrected and covered
by the final passing run. These are development checks, not reference-device or real speech model acceptance.

M21's [rendered capture evidence](../../evals/perception/runs/2026-10-15/README.md) remains 20/22 exact transcription,
with ordinary-camera, calibration, signed-pack and device gates open. All voice release limitations listed above still
apply, including actual speech packs, microphone/speaker/device evidence, read-aloud and dictation.

## Combined M21 integration verification

Integrated after M21 `d13a2838` and foundation merge `374435a4`, preserving the shared rich editor, accounting
input, persistent drafts, photo capture and both camera and microphone native permissions. The follow-up source is
`7ee1b2d3`. M21 and voice generated bindings were regenerated together from the combined private specification.

- Combined M21/voice/profile/perception regressions: **777 Python tests passed**, including the five pinned upstream
  protocol cases. Two focused capture-promotion and safe-mark regressions passed again after final draft handling.
- Client **117**, UI **109**, desktop **40** tests passed (**266 total**), including failed confirmation, duplicate Send
  and session-switch races. All three TypeScript workspaces passed typechecking.
- Strict mypy: **400 source files**; Ruff and ESLint passed. Dependency Cruiser found no violations.
- Contract regeneration, fixture generation (457 fixtures), schema/data inventory/spec-lock/eval-lock checks,
  architecture layer/import rules and licence/notice/dependency checks passed. Native shell `cargo check --locked`
  and the desktop production build passed; the existing large JavaScript chunk advisory remains.

These tests use synthetic audio and protocol endpoints, not installed speech models or real-device microphones.
Speech-pack capability gates, the 300-utterance accuracy gate, signed bundle and device-dependent release checks
remain open. This integration does not complete M31/M32 acceptance.

## Student integration reconciliation

The merge retains main's confirmation/session-switch protections, rich maths/accounting editor, drafts, photo handling,
student-text provenance for voice captures, and both camera and microphone permissions. Home Ask uses the same
explicit confirmation and `capture_id` path, including when the session already has turns. Note Save has a synchronous
in-flight guard and preserves the editable transcript after failure. Notes never enter the tutor capture repository.

Migration 4 is appended after unchanged migrations 1–3. It preserves captures, rich drafts and settings, adds
`study_notes` and the voice preferences, and is covered by forward migration and sealed export/import regressions.
The study-note retention rule and per-column data inventory are included; routine retention keeps notes until
explicit deletion or profile deletion. Earlier and newer specification text is preserved in the combined private pin.

Real speech-model accuracy, signed speech bundles, real-device microphone/camera/OS-voice behaviour, automatic
screen-reader detection/ducking and the existing M25 → M31 → M32 release gates remain unverified. No M31/M32 release
acceptance is claimed. The desktop build retains its existing large-JavaScript-chunk advisory.

Final integration verification: **829 combined Python tests passed**, with no deselected native photo smoke test;
**123 client, 113 UI and 42 desktop tests passed (278 total)**. The 10 student-voice tests also passed as a focused
run, including the sealed note/preference round-trip. Typechecks for all three frontend workspaces, ESLint, Ruff,
strict mypy (402 source files), Dependency Cruiser, codegen drift, 469 generated contract fixtures, storage inventory,
spec/schema/eval locks, licence/notice/dependency checks and all 31 import architecture contracts passed. The native
shell compiles with `cargo check --locked`; the desktop production Vite build passes. These results use synthetic
fixtures, local protocol endpoints and installed test tooling, not real speech models or reference-device acceptance.

Voice review follow-up (D88, SEC-12a, SEC-16): a speech pack is a `speech_pack` artefact that only an
updater-purpose intermediate may sign, separate from the model-only signing role. Core scans, installations, reuse of
a running sidecar and sidecar startup apply the device's adopted root-signed revocation list (`config/revocations.json`
in the data folder). The native supervisor independently verifies the embedded trust chain, the updater purpose, the
signing time, the environment, the newest valid revocation list and the signed entrypoint hash before executing a
speech bundle or restarting it.

Safety flags and calm-screen notices are delivered independently of provisional speech playback (VOC-20, PRV-14):
`ProvisionalVoiceTurn.salvage_safety()` delivers them once, ahead of release, and a later release or discard never
repeats them. Closing voice, cancelling unheard audio, transport loss or closing the profile preserves those effects
exactly once (never into another profile's database), a distress turn is never carried forward or replayed as typed,
voice then rests idle until the client re-sends its talk mode, and unaccepted lesson state remains discarded. Voice
keyboard shortcuts yield to controls, dialogs, composition and modified shortcuts; a reason without student copy
maps to the VOC-14 "Voice stopped working" copy, never a raw key.
