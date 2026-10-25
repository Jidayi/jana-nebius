# Jana — Nebius × NVIDIA

An offline-first secondary school sciences tutor for Mathematics, Physics, Chemistry, Biology and Accounting.
This monorepo contains the local tutor, checking worker, desktop shell, curriculum tooling and S2 implementations.
Desktop installation controls and typed input are being integrated. This fork preserves the original implementation; passing development tests does not constitute release acceptance.

## Layout

| Path | Holds |
| --- | --- |
| `apps/desktop/` | Desktop app: `src-tauri/` (Rust shell) and `src/` (React entry) |
| `apps/prototype-s0/` | The S0 prototype, frozen and excluded from releases |
| `packages/` | `ui`, `client-core`, `renderers`, `contracts-ts` (generated), `i18n` |
| `services/` | `agent-core`, `tool-worker`, `perception-worker`, `pack-builder` and, later, online services |
| `content/`, `skills/` | Authored agent content, curriculum sources and skills |
| `evals/` | Evaluation suites, fixtures and contract corpora |
| `scripts/` | Repository tooling (`jana_tools`), git hooks and CI scripts |
| `docs/` | Private specification; deliberately absent from this hackathon copy |

An unknown directory fails the layout check. Every package declares its layer in its manifest
(`jana` in `package.json`, `[tool.jana]` in `pyproject.toml`, `[package.metadata.jana]` in `Cargo.toml`).

## Hackathon copy

This is a fresh source copy of Jana for the Nebius × NVIDIA Global AI Hackathon. The original desktop app,
shared UI, themes, navigation, feature implementations and authored curriculum are preserved. The separate
custom browser demo from the previous attempt is not part of this checkout. No upstream Git history, remote,
secrets, private specification or internal deployment evidence was copied.

The cloud provider now routes Coach and Diagnoser to NVIDIA Nemotron Super and Solver and Checker to
Nemotron Ultra through Nebius Token Factory. The gateway alone reads `NEBIUS_API_KEY`; the UI does not receive it.
The browser host reuses the original app and native runtime, profile isolation, consent gates, maths checking,
Study workspace and signed curriculum packs. It sends authenticated requests to the owner's local gateway; no
scripted provider is installed in this mode. Study generation is **online-only**. Saved material and study aids
remain on the device. Cloud voice is not connected by this host.

Saved source learning journeys connect a lesson, its flashcards and its quiz through durable profile-local links, including existing linked sets. Home and Study show the same next step, using actual card reviews, saved quiz drafts and submitted results. Completed quiz feedback survives reopening; questions needing another look lead back to the lesson before an explicit retry. Reading or revealing content never counts as a card review or O-level mastery. Journey links survive job cleanup and follow the source’s existing private-access, archive and erasure rules.

The [25 October feature import](FEATURE_IMPORT.md) adds Jana's tutor pen, annotations, diagram manipulation,
sketches and additional science visuals. Parent summaries and alerts are in Settings; retained session history is
under Progress. Authoring analytics are in Studio. The browser development host exposes these imported screens
at stage S3 while retaining this fork's provider and learning-journey integration.

Ask anything can retrieve public evidence with Tavily Search and Extract, then use Nemotron to draft an answer
and check its cited support. Each question requires the existing web-search confirmation. Study can also import
a public HTTPS page after a separate confirmation; uploaded files and private notes are never sent to Tavily.
The gateway alone reads `TAVILY_API_KEY`. Live browser checks verified Search and Extract using existing credits,
followed by Nemotron generation and a separate support check. Web source rows open the original public pages.

File extraction also uses the online Study gateway (up to 300 PDF pages). Study checks profile access before
processing, keeps uploads locally while approval is pending, and links to the relevant consent settings. Returning
from those settings restores the selected source; no consent or file transmission is automatic.

Study processes whole documents in automatic 16,000-character batches and combines their checked results.
Keeping all detected topics selected includes the whole document, including chapters beyond the heading preview.
Verified batches are checkpointed so interrupted work can resume without repeating them; an unfinished batch
cannot publish a partial aid as complete. Search answers and their sources appear above Home's message input.
Summary, Notes and Podcast verification checks each claim independently; flashcards and quizzes check complete cards and
question/key pairs, keeping only supported items while requiring safety approval for the entire batch.
Model requests preserve all source text but use short citation references instead
of repeating quoted passages. Citation links scroll directly to the highlighted excerpt, including in long PDFs.

Live Study checks extracted all 69 pages of `notes.pdf`. A fresh whole-document Nemotron Ultra run with every
topic included and no focus restriction completed six automatic batches (81/81 processing steps), producing
24 supported summary points with 44 exact source citations. Every citation matched the stored PDF text;
browser checks opened highlighted passages on pages 9, 37 and 68. Interrupted runs also resumed verified batches.
Whole-document flashcards completed the same six batches and produced 10 cards with 24 exact citations.
Browser checks revealed card backs, opened the cited PDF passage and saved a Good review, leaving nine cards due.
Reviewed PDF extraction does not require a second confirmation to rate its saved cards; revision checks still apply.
Two whole-document quizzes also completed 81/81 steps. The fresh default quiz has 10 questions (six choice,
three fill-in blanks and one true/false) with 28 exact question/explanation citations, including late chapters.
Browser checks submitted all 10 source-worded answers successfully, and separately exercised wrong-answer
feedback, explanation reveal, skipped answers and PDF source links. The queue preserves deterministic marking
for choices, multiple selections, true/false and literal blanks instead of replacing it with a fallback verdict.
Blank answers keep normalized exact matches fast. Other wording uses the local NVIDIA marker on the question's
cited passages, then a separate source-entailment check of the completed sentence without the first verdict or
answer key. Both passes must agree before accepting or rejecting an answer; unavailable models, ambiguity or
disagreement leave it unverifiable. The saved explanation keeps its original verified citations. These judgments
retain the “Judged, not checked” label and never alter syllabus mastery. Live browser checks accepted “exponentially,”
“the input depth,” “at an exponential rate” and “the matrix V” in the whole-PDF quiz, while rejecting a changed quantity,
reversed negation and instructions embedded in a wrong answer. No extra Nebius inference was needed.
Generated blanks prefer words and short concepts rather than formulas; semantic grading is not a deterministic
mathematical proof. Saved quiz keys stay out of the pre-submission public view.
Whole-document Notes and standard Podcast also completed six batches (81/81 steps). Notes produced 46 cited
points with 65 exact citations; Podcast produced 20 spoken passages with 51 exact citations. The browser opened
highlighted Notes and Podcast source passages on pages 66 and 65, and Podcast playback advanced through six
passages before Stop returned it to Play. Verified Podcast batches resumed without being regenerated.
Podcast Play/Stop supports NVIDIA Magpie neural narration through the gateway, using its free API-catalog
prototype endpoint. Only the verified, verbalised script is sent in bounded passages; the browser never receives
a provider key. NVIDIA’s trial can retain inputs and audio, as disclosed beside Play, so private-marked sources
are refused and confidential material should not be used with the trial. Audio remains in memory in Jana.
The live browser check on October 23 read the NVIDIA key from Keychain, played successive passages of the
whole-PDF Podcast with Magpie, and verified Stop during playback and while a cloud response was pending.
The subsequent uninterrupted UI run completed all 20 passages: 20 new NVIDIA responses completed, with no held
speech requests or playback error, and Play returned automatically at the end. Loading gaps between passages
remain; this establishes automatic completion, not gapless playback. Recorded inference stayed at $2.492448.
Study now offers quick generation with separate settings, duplicate-set reuse, summary presets with source-page
sections, and focused quiz navigation with native single-question feedback; the all-questions view remains available.
Old failed and paused jobs stay in collapsed history below results, while a newly failed request stays actionable.
Podcast buffers at most one passage ahead in memory and provides Pause/Resume, Jana's existing progress bar and
an explicit finished state. Stop/profile changes discard late audio; playback and Resume recheck native access.
The updated UI completed all 20 Podcast passages after Pause/Resume. A whole-PDF Cheat sheet completed 81/81 steps,
with 30 points and 56 exact source citations. Recorded inference reached $2.601053; existing unresolved holds remain.
Existing Voice controls are now available inside Accessibility settings
when the core does not advertise a separate Voice section; later-stage builds keep the single original section.
A public documentation page imported through Tavily produced two cited flashcards in an earlier live check.
Some websites refuse extraction; use a file or pasted text when that happens. These checks do not establish that
every aid, recording or YouTube URL works.

The approved budget is **$25 total for ten days**: $15 inference and $10 reserved for hosting. The gateway's
persistent ledger at `/tmp/jana-nebius-gateway` is retained across this reset. The supplied configuration limits
inference to $4 per UTC day and $15 total, ending November 2, 2026 at 00:46:01 UTC. The daily ceiling allows
live qualification within that same total; subsequent days share the remaining allowance. It reserves in-flight costs
and retains failed or unresolved reservations. Do not delete or reset that ledger. Tavily has a separate durable
limit of 50 existing credits per UTC day and 500 total, with the same expiry. It uses basic Search/Extract only,
checks the account's available prepaid credits and refuses requests when paid overage is enabled or usage cannot
be verified. It never purchases credits. Conversational cloud voice remains disabled. Podcast narration uses
NVIDIA’s free prototyping access, with a separate durable limit of 20,000 characters/100 requests per UTC day
and 100,000 characters/500 requests total through the same expiry. Unknown sends remain counted. It never
provisions a GPU, purchases credits or selects a paid speech endpoint.

For local development, save the provider keys once in **macOS Keychain Access**, in the login keychain:

| Keychain Item Name (service) | Account Name | Password |
| --- | --- | --- |
| `jana-nebius.cloud-gateway` | `nebius_api_key` | Your Nebius Token Factory key |
| `jana-nebius.cloud-gateway` | `tavily_api_key` | Your Tavily key |
| `jana-nebius.cloud-gateway` | `nvidia_api_key` | Your free NVIDIA API catalog key |

Choose **File → New Password Item** for each row and enter the actual key only in its Password field.
This dedicated service name keeps the hackathon's credentials separate from other Jana installations.
The gateway already reads these items directly; no key file, shell export or frontend change is needed.
macOS may ask you to approve Keychain access when the gateway starts. Only approve a lookup you initiated.
If that lookup times out, open that specific item’s Access Control and permit `/usr/bin/security` for the item;
do not allow all applications. Restart the gateway after changing access. No key needs to be copied to chat.

Start the gateway from any Terminal:

```bash
uv run --offline python -m cloud_gateway --config services/cloud-gateway/deploy/nebius-dev.toml --port 8081
```

Gateway-only environment variables remain supported as a temporary alternative. They take precedence over
Keychain items. After saving the items, clear old exports in the gateway Terminal with
`unset NEBIUS_API_KEY TAVILY_API_KEY NVIDIA_API_KEY` before starting it to use Keychain.

For GCP deployment, use Google Secret Manager and mount the secrets into the gateway's configured
`secrets_dir` as `nebius_api_key`, `tavily_api_key` and `nvidia_api_key`; the gateway supports this source already.
See [Cloud Run secret configuration](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

Do not paste provider keys into chat, a repository file, browser storage or frontend configuration.
Provider adapters load keys at startup, so replacing a key or changing gateway code still requires a restart;
Keychain removes the need to re-enter keys or keep a particular Terminal session alive.

Start the full app's live hackathon browser host in a second Terminal:

```bash
uv run --offline python -m jana_tools.hackathon_dev
```

Open **http://127.0.0.1:5187/**. The separate port avoids another app already using 5173 on the development machine.
The first launch builds and verifies all four original signed subject packs; later launches reuse the cache.
Create a synthetic demo profile. In Settings → Online features, give the cloud tutor consent. Accept its native
first-use notice when asking a question. For online Study, an adult profile can give its own material consent in
the same settings section. Minors retain the existing signed guardian-checkout requirement; the sponsor never
invents that consent. A device switch alone does not grant a minor permission to transmit material.

The host provisions only a native device public key for the sponsored development access. Its private device key
stays outside the app data directory, under a private file keystore; the gateway issues short-lived device tokens.
Normal restarts reuse that credential, respect the existing device limit and never revoke other credentials.
Ending sponsored access is sticky. This local host is development-only; public deployment still needs a reviewed
hosting and authentication configuration. No cloud deployment or video publication has been performed.

### NVIDIA offline tutor

The optional local tutor uses NVIDIA's official [Nemotron Nano 4B Q4_K_M](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF)
with the installed llama.cpp runtime. The launcher verifies the published SHA-256 before loading, binds the runtime
to literal loopback, creates a private per-launch key and connects it through the original native control protocol.
Readiness requires a real tool-template generation. Local calls have no API cost. Its quality and performance still
need broader evaluation; loading a model does not qualify a release.

After downloading NVIDIA's official GGUF to a local path, use:

```bash
uv run --offline python -m jana_tools.hackathon_dev --local-model /path/to/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf
```

The expected SHA-256 is `be5d9a656a51922f24f1f09a759cebb694e1f5d9728bf0ef9f8c972c5a0b5ef2`.
Model use is governed by the [NVIDIA Nemotron Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license/).
The launcher never downloads weights automatically and removes both provider keys from its child environments.
Cloud routes remain available after attaching the local model, subject to the original consent and budget gates.

Plain `pnpm --filter @jana/desktop dev` retains the original scripted UI-development mode. Use the launcher above
for the real hackathon integration. Scripted replies must never be presented as live NVIDIA inference.

The [hackathon rules](https://nebiusglobalaihackathon.devpost.com/rules) allow substantially updated existing projects.
The submission should distinguish the preserved Jana foundation from the NVIDIA, Nebius and hackathon work.

## The specification

The original private specification is excluded from this fork, together with its pin and internal run evidence.
Never copy it into this repository. Public wire contracts and generation inputs live in `contracts/`; the unchanged
UI token values live in `packages/ui/tokens.json`. CI regenerates the bindings and checks for drift. Governance-tool
tests use explicitly synthetic fixtures in `scripts/tests/fixtures/governance`, while release gates refuse missing
owner decisions and evidence. A passing test run does not grant release approval.
The existing guard hooks can still prevent accidental inclusion:

```bash
git config core.hooksPath scripts/git-hooks
```

## Checks

Run every installed toolchain without network access:

```bash
./scripts/ci/run-all-tests.sh
uv run --frozen --offline python -m jana_tools codegen --check
uv run --frozen --offline python -m jana_tools fixtures --check
```

Focused hackathon integration checks:

```bash
uv run pytest services/cloud-gateway/tests/test_nebius.py services/cloud-gateway/tests/test_inference_budget.py -q
pnpm --filter @jana/desktop typecheck
pnpm --filter @jana/desktop build
```

Acceptance tests are named after the specification's test names, for example `arc16_repository_layout_check`.
