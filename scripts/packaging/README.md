# Packaging

The release job's build inputs for the desktop app (PLT-02 to PLT-07, PLT-14, DSN-25). `build-sidecars.sh` builds the
agent core and tool worker one-dir bundles with PyInstaller (`*.spec`), fetches the pinned llama.cpp builds and stages
everything under `apps/desktop/src-tauri/resources/` for `cargo tauri build`. The CI jobs `packaged-smoke` (development
signing) and `release` (production signing) in `.github/workflows/ci.yml` run it.

On Windows a second pass builds the USB kit's installers with `tauri.usbkit.conf.json`: the per-user NSIS installer
and the per-machine MSI for schools (PLT-06, PLT-21) both carry the WebView2 offline installer, so either installs
with no network (PLT-06, PLT-12). Both passes write the same file names, so the offline-capable installers are the ones
the job keeps. The installer's own words are keys of `apps/desktop/src-tauri/installer/strings.json` (LOC-01); after
changing it run `uv run python -m jana_tools installer-strings --write`.

## Pins

`uv run python -m jana_tools release pins` lists every value still marked `PLACEHOLDER` that a development-signed
packaged build needs; `--release` adds what a signed release needs. While any build pin is a placeholder, the
`packaged-smoke` stage runs only the installer precheck and the icon check; `release` refuses to start.

Each pin below has one owner. Engineering pins only need the network. Owner and infrastructure pins are decisions or
secrets, so engineering cannot fill them.

### Engineering (needs the network, not available offline)

- [x] **Build tools** (`requirements-build.txt`): run the command in `requirements-build.in` to record exact versions
  and PyPI hashes. Then add a review entry for each new package to `dependency-reviews.toml` (SEC-22).
- [ ] **Tauri CLI** (`tauri-cli.version`): use the `tauri-cli` release that goes with the `tauri` crate in
  `Cargo.lock` (2.12.x on 2026-10-15). `cargo install tauri-cli --locked --version <it>` must succeed.
- [ ] **llama.cpp builds** (`../release/runtime-builds.toml`): set the upstream release tag and its full commit. Then
  set each archive's sha256 from the release's published checksums, checked against a second download. The release
  should be the one the device lab benchmarked (PLT-04, PLT-08).

### Owner (product owner or platform lead; decisions and identities)

- [ ] **Publisher and copyright** (`tauri.release.conf.json` `publisher`, `copyright`): the legal entity's exact name.
  The Windows installer and the macOS bundle show it, and the Authenticode certificate's subject must match it.
- [x] **Short description** (`tauri.release.conf.json` `shortDescription`): "A personal tutor for secondary school
  students." — approved by the product owner on 2026-10-17 (D60: no exam level; offline is not the product's identity;
  "sciences" dropped because the tutor also covers mathematics and accounting).
- [ ] **Developer ID identity** (`tauri.release.conf.json` `macOS.signingIdentity`): the certificate's name, as in
  `Developer ID Application: <entity> (<team id>)`.
- [ ] **Notarisation team** (`tauri.release.conf.json` `macOS.providerShortName`): the Apple team ID.
- [ ] **Updater public key** (`tauri.updater.conf.json` `plugins.updater.pubkey`): the update-signing key from the key
  ceremony's step 8 (SEC-12, G107). Its private half never leaves the offline ceremony laptop's updater stick: app
  updates are signed offline (owner ruling 2026-10-17; see "App updates, signed offline" below). The release trust
  anchors (`trust_anchors.json`) come from the same ceremony.
- [ ] **Antivirus products** (`../release/antivirus-products.toml`): the three products the pilot device survey finds
  most common (PLT-07).
- [ ] **Release artwork** (DSN-25): signed-off icons in place of the placeholder (`release icons --release`).

### Infrastructure (hosts, HSM and CI secrets)

- [ ] **Authenticode signing** (`tauri.release.conf.json` `windows.signCommand`, `windows.timestampUrl`): the HSM
  vendor's sign command, run on `%1`, with `JANA_AUTHENTICODE_KEY_REF` and `JANA_AUTHENTICODE_CREDENTIALS`. Also the
  certificate vendor's RFC 3161 timestamp URL. Every `.exe` and `.dll`, sidecars and runtime included, is signed
  and timestamped (PLT-05).
- [ ] **Update host** (`tauri.updater.conf.json` `plugins.updater.endpoints`): the production update host. The path
  (`/v1/check/<channel>/{{target}}/{{current_version}}`) is fixed.
- [ ] **CI secrets** for the `release` environment: `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_API_ISSUER`, `APPLE_API_KEY`, `APPLE_API_KEY_PATH`, `JANA_AUTHENTICODE_KEY_REF`,
  `JANA_AUTHENTICODE_CREDENTIALS`, and `JANA_SPEC_DEPLOY_KEY` for every stage. There is no updater key secret: CI
  never signs an app update.
- [ ] **Release runners and the device lab**: these produce the evidence that `scripts/tests/test_m20a_packaging.py`
  and the M20 pack tests read, and each test skips until its evidence exists:
  - `JANA_PACKAGED_RESULTS`: the `packaged-smoke` reports, including the Windows 10 USB-kit run without WebView2
    (`plt01`, `plt06`);
  - `JANA_BUNDLE_DIR` and `JANA_PACKAGED_APP`: signature audit and Gatekeeper (`plt05`);
  - `JANA_AV_RECORD` and `JANA_RELEASE_SHA256SUMS`: the antivirus record (`plt07`);
  - `JANA_DEVLAB_RESULTS`: the low-class laptop's USB install time and 20-turn memory peak (`plt12`, `plt23`).

## App updates, signed offline (SEC-12, SEC-15, PLT-14)

Owner ruling 2026-10-17: the Tauri updater key is never in CI. The release job builds with
`tauri.updater.conf.json` (the app's updater public key and endpoints; `createUpdaterArtifacts` is off, so the build
needs no key), then leaves each OS's update bundles unsigned in `update-request-<os>` with a request listing their
sha256 (`python -m signing_service.updater request`), uploaded as the run's `update-request-*` artefacts. On Windows
the request is taken after the first build pass, before the USB-kit pass replaces the installers.

The release manager signs them on the offline ceremony laptop with `python -m signing_service.ceremony sign-updates`
(steps in `scripts/governance/evidence/KEY-CEREMONY.md`, "Signing an app update"), which writes
`update-signatures.json` and Tauri's `latest.json`. Publishing takes only that result:
`python -m signing_service.updater verify <folder>`, then `python -m jana_tools release publish <bundle> --kind
app_update ... --signatures <folder>/update-signatures.json` per bundle, which refuses a bundle the result does not
sign or whose signature does not verify against `plugins.updater.pubkey`. The offline update pack (`.janaupdate`) is
signed separately, by the Updater intermediate of the Ed25519 hierarchy (TABLE SEC-12a).

## Linux worker sandbox (SEC-06, TABLE SEC-06a)

The tool and perception workers run under bubblewrap, with the Landlock fallback where bubblewrap is missing or cannot
create its namespaces (unprivileged user namespaces disabled). A release build never starts a worker without one of
the two: the checks are then unavailable and the health panel shows the sandbox degraded.

- `.deb`: `bubblewrap` is a package dependency (`tauri.release.conf.json`), so apt installs it with the app.
- AppImage: an AppImage cannot declare dependencies. On a machine without `bwrap` the workers use Landlock (Linux 5.13
  or later with Landlock enabled, which current Ubuntu, Debian, Fedora and Mint kernels are); on an older kernel the
  school's IT installs `bubblewrap` from the distribution (`sudo apt install bubblewrap`). The school IT guide (OPS-25)
  should say so.
- Ubuntu 24.04 and later restrict unprivileged user namespaces through AppArmor; the distribution's `bwrap` profile
  allows bubblewrap, and where a hardened machine removes it the Landlock fallback applies.

## English speech pack (VOC-03, D95, D88)

The speech pack is built outside the repository from files already on the build computer: the owner-approved
voices with their download manifests (`~/.jana/models/speech`), the two speech runtimes resolved offline from the
approved wheels (`~/.jana/speech-env/pack-runtimes/{kokoro-cpu,qwen3-mlx}`), spaCy's `en_core_web_sm` inside the
Kokoro runtime, the uv-managed CPython 3.12 and this repository's launcher code. Nothing is downloaded.

```bash
uv run python -m jana_tools.release.speech_pack build --version 1_0     # -> ~/.jana/release/speech/sp.en.1_0, unsigned
uv run python -m jana_tools.release.speech_pack check ~/.jana/release/speech/sp.en.1_0
```

The pack ships the native sidecar, so only the Updater key signs it (D88). The signing command re-runs the licence
gate and hashes every file before it signs, and reads the signed manifest back:

```bash
# Production (after the key ceremony has issued the updater intermediate into the trust anchors):
cd services/signing-service
uv run python -m signing_service sign-speech-pack ~/.jana/release/speech/sp.en.1_0 \
    --key-id <updater intermediate key id> --hsm-command "<the HSM's signing command: bytes on stdin, base64 out>"
# Development builds only (the test hierarchy):
uv run python -m signing_service sign-speech-pack <a copy of the pack> --dev
```

A signed pack installs like any pack: Settings → Packs → Install from a USB stick or folder (`POST /v1/packs/install`
with `{"kind": "usb", "path": ".../sp.en.1_0"}`), or listed under `speech/sp.en.1_0/` in a USB kit's signed `kit.json`.
The installer copies only the device's class (1.3 GB low and mid, 3.1 GB high) and read-aloud uses the pack's voice
at once, without a restart. `python -m jana_tools.release.speech_pack_e2e <dev-signed copy>` checks a pack end to end
on a development computer (scripted tutor, real voice, time to first audio).

## Files

| File | Holds |
| --- | --- |
| `build-sidecars.sh` | The release job's sidecar build, runtime fetch and resource staging (refuses placeholders) |
| `*.spec` | PyInstaller one-dir specs: agent core, tool worker, perception worker (separate pack), voice sidecar |
| `requirements-build.in`, `requirements-build.txt` | The build-only tools, and the same compiled with hashes |
| `tauri-cli.version` | The Tauri CLI version the jobs install |
| `voice-upstream.json` | The voice sidecar's pinned upstream |

## Internal Studio runtime

`build-studio.sh` builds an independent authoring backend and tool worker using the hash-pinned build tools. See
`apps/studio/README.md` for required Node/notice inputs, the frozen smoke test, the native resource overlay and
the outstanding platform/signing evidence. Studio resources never enter the learner bundle.
