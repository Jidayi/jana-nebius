# agent-core

The agent core sidecar (`agent_core`, Python 3.12; D19). Most subpackages are placeholders until M3–M5; each exists
so the layer rules (ARC-01, ARC-18) apply from the first commit. Layers are declared in `pyproject.toml`.

| Module | State |
| --- | --- |
| `agent_core.contracts` | GENERATED from the specification's schemas (M1): Pydantic models, bundled schemas, `validate`/`errors`, and the compatibility runtime (`_compat`: versions, Meta.protocol negotiation, tolerant event reader). Never edited by hand; `python -m jana_tools codegen`. |
| `agent_core.config` | Typed, layered configuration (ARC-27, ARC-28): every key declared once in `keys.py` with its type, default, unit, range, allowed layers and the requirement it serves; `resolve()` applies the eight layers, the restrict-only safety layer and release-build rules; `check_write()` returns locked reasons; `environments.py` holds the OPS-35 environment policies. |
| `agent_core.trace` | The engine scope every model call runs in (ARC-20). |
| `agent_core.engine` | `turn_scope` and `job_scope` (ARC-20); the turn engine arrives in M4. |
| `agent_core.router` | `complete`/`stream` refuse to run outside an engine scope (ARC-20); providers arrive in M3. |

Proposal values from the specification are configuration keys, never literals in code: add the key in
`agent_core/config/keys.py` when code first uses the value (`uv run python -m jana_tools proposals` reports coverage).

Session notes (STU-14) use learner migration 9 and a durable local queue in `engine/session_notes.py`. The model selects
evidence numbers and sections; it cannot supply note prose. The core materialises screened excerpts from completed
tutor parts, with turn references, and never updates mastery. Jobs wait for the local model and foreground work,
recover after restart, and stop on profile changes. Safety sessions are withheld. Deleted projections keep empty
tombstones so backlog recovery and archive restoration cannot recreate them.

The optional `/v1/session-notes` routes list/search, open after private confirmation, mark private, retry generation
and delete. `POST /v1/sessions/{session_id}/end` ends the learning session without deleting its history. These additions
are implemented with explicit profile scope and input-route declarations; their request/response types currently
live in the engine/API and client adapters pending canonical contract reconciliation. Profile archive payload v2
preserves session notes and empty tombstones; readers still accept v1. Older readers refuse v2 rather than losing notes.

Assessment presentation rejects unavailable diagrams and account charts before selecting questions. Numbered assessment diagrams strip answer-bearing library metadata and SVG labels, remap private part IDs, and require an authored alternative that does not disclose requested labels. Lesson checks share these presentation and answer adapters. Short text remains explicitly unmarked and cannot enter automatic diagnostic/mastery selection.


### M42 local study preview

`JANA_STUDY_WORKSPACE_ENABLED=true` enables the local study workspace in a development launch. The default is
false; release builds ignore this developer override. The core advertises `study_workspace` in `/v1/meta` and the
desktop shows **Study** only with that capability. This does not advance the build stage or enable online features.

The current slice accepts pasted text and local PDF, TXT/Markdown, DOCX/ODT and PPTX/ODP files. Uploads use bounded
hashed chunks; extraction runs in a disposable network-denied process, with 30 pages/slides and 100 MiB input limits.
Text, Unicode citation ranges and immutable revisions live in the profile's learner database. A local model generates
notes, summaries, flashcards or choice quizzes, followed by a separate source-support check. Invalid citations and
unsupported output fail closed. Quiz keys stay out of student replies; source-card FSRS reviews and generated quiz
results never change syllabus mastery. Interrupted uploads can be resumed by selecting the same file. Source-text
corrections create a new revision; old citations remain readable and old aids become stale.

The migration adds learner database version 10 and makes the normal migration backup. An older binary that only
understands version 9 will refuse the migrated profile; keep the backup when testing rollback. No tutor, existing
notes or syllabus records are rewritten by this migration.

This is a preview, not M42 acceptance or a production rollout. Still outstanding: encrypted archive integration and
old-archive deletion semantics; cloud consent/quota/ephemeral-file protocol; scanned-page OCR and sanitized page
rasters; recordings, audio overview and source chat; complete slide/speaker-note handling; large-source hierarchical
generation; native partial-extraction confirmation; complete accessibility/gallery and reference-device qualification.
Local generation currently bounds source text at 48,000 characters and rejects longer requests rather than truncating
silently. General free-response grading remains unverifiable. Source files are untrusted data and never instructions.

`tests/test_study_workspace.py` covers real SQLite/API lifecycles, the actual sandboxed PDF process and structured
local-router generation/support with scripted replies. It does not measure the quality of a live model or qualify the
frozen application on Windows/Linux/macOS. Existing encrypted profile exports currently omit workspace materials;
do not use this preview as the only copy of teaching material.
