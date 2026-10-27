# Jana — powered by Nebius

Jana connects a daily learning plan, curriculum lessons, checked practice, tutor help and Study from a learner’s own materials. Lessons, saved progress and completed Study aids remain available on the device. Online tutoring and Study processing use the budgeted Nebius gateway.

## Learning journey

1. Select a learner profile and start from Home’s next learning objective.
2. Read the linked lesson, then try practice on the same objective.
3. Ask the tutor for help and return to the exercise with its context intact.
4. Upload notes or a scanned PDF, compare the extracted text with the original pages, and confirm the readable passages.
5. Ask a source-based question or generate study tools. Citations open the original evidence; saved flashcards, quiz attempts and learning journeys can be resumed.
6. Review progress and session history. Settings also includes local parent summaries and alerts; authoring analytics are available in Studio.

The recording profile is **Alex Morgan**, a fictional adult learner. Use synthetic notes for the demo. The bundled [two-page scanned PDF](evals/perception/handwriting/demo-scanned-notes.pdf) contains image-only maths and biology notes. Automatic transcription, original-page previews and a page-2 cited answer were verified through the actual app upload flow. This sample does not establish accuracy for every handwriting style.

## Nebius architecture

| Responsibility | Route |
| --- | --- |
| Coach and diagnosis | Nemotron Super on Nebius Token Factory |
| Solving, checking and Study generation | Nemotron Ultra on Nebius Token Factory |
| Scanned-page transcription when printed OCR is insufficient | MiniCPM vision reader on Nebius Token Factory |
| Optional offline tutoring and local marking | Local Nemotron runtime |
| Optional public web search/import | Tavily, with separate confirmation |
| Optional podcast narration | NVIDIA Magpie prototype service, with its own disclosure and limits |

Concrete model IDs, prices and the provider endpoint are in [gateway defaults](services/cloud-gateway/cloud_gateway/defaults.toml). [nebius-dev.toml](services/cloud-gateway/deploy/nebius-dev.toml) controls the local demo. Credentials stay in the gateway; the browser never receives provider keys. Cloud conversational voice is disabled in this host.

## Run the demo

Save the configured keys in macOS Keychain Access, in the login keychain, using service **`jana-nebius.cloud-gateway`**:

| Account | Used for |
| --- | --- |
| `nebius_api_key` | Nebius Token Factory |
| `tavily_api_key` | Optional public web search/import |
| `nvidia_api_key` | Optional podcast narration |

The optional gateway environment names are listed in [.env.example](.env.example). Do not put credentials in source files, browser storage, command arguments or recordings. The gateway reads its secret source at startup.

Start the gateway:

```bash
uv run --offline python -m cloud_gateway --config services/cloud-gateway/deploy/nebius-dev.toml --port 8081
```

In a second terminal, start the app:

```bash
uv run --offline python -m jana_tools.hackathon_dev --stable --port 5187 --data-dir /path/to/demo-data
```

Open **http://127.0.0.1:5187/**. Reuse the same data directory to retain profiles. `--stable` builds once and serves the preview. The host installs the signed subject packs and uses the real gateway. The plain desktop Vite development command uses scripted replies for UI development; use the launcher above for a live demo.

For the optional offline tutor, add `--local-model /path/to/model.gguf`. The launcher verifies the supported [Nemotron Nano 4B Q4_K_M](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF) before loading it through llama.cpp. The expected SHA-256 is `be5d9a656a51922f24f1f09a759cebb694e1f5d9728bf0ef9f8c972c5a0b5ef2`. Model use follows the [Nemotron Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-nemotron-open-model-license/).

Online features require the selected profile’s consent and first-use confirmation. Adult profiles can review Study consent in Settings → Online features. Minors retain the signed guardian-consent requirement. Scanned notes are initially unreviewed; generation requires confirmation of the extracted passages.

## Demo limits and deployment

The existing approval allocates **$15 total to inference**, with **$10 reserved for hosting**. The active configuration permits at most **$6 per UTC day** within that same inference total and expires on **2 November 2026 at 00:46:01 UTC**. Hosting purchases require separate authorization. The durable ledger at `/tmp/jana-nebius-gateway` preserves actual spend and uncertain reservations across restarts; never delete or reset it to recover allowance.

Tavily uses existing prepaid credits with separate daily/total caps. Podcast narration uses the existing free prototype access with bounded characters and requests. Neither integration purchases credits or provisions a paid endpoint. Private-marked sources are excluded from the narration trial because it may retain text and audio.

This is a local development host. Public hosting, production retention evidence, authentication, native distribution and independent acceptance require their own qualification. See [gateway deployment](services/cloud-gateway/deploy/README.md). Current verification and its limits are recorded in [FEATURE_IMPORT.md](FEATURE_IMPORT.md); detailed engineering observations are retained in [DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md).

## Repository

| Path | Purpose |
| --- | --- |
| `apps/desktop` | React app and Tauri shell |
| `apps/studio` | Curriculum authoring and analytics |
| `packages` | Shared UI, client logic, renderers, contracts and translations |
| `services` | Agent core, gateway, sandboxed workers and curriculum tooling |
| `content`, `skills` | Curriculum and teaching content |
| `evals` | Fixtures, evaluation suites and recorded model provenance |
| `scripts` | Development, verification, packaging and release tooling |

Public wire contracts and generation inputs live in `contracts/`; UI tokens are in `packages/ui/tokens.json`. Private specifications, credentials, model weights and learner data are excluded from Git. Keep third-party licence notices with distributed components.

## Project provenance

This application builds on the Jana learning foundation. The hackathon integration adds Nebius routing, bounded cloud inference, connected learning journeys and the subsequent feature work described in [FEATURE_IMPORT.md](FEATURE_IMPORT.md). Historical provider adapters, frozen evaluation inputs and model-generation receipts retain their actual provenance; they are not instructions for the current demo or claims of new Nebius runs.
