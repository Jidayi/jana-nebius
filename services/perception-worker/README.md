# Perception worker

M21 printed-photo preprocessing and OCR. One image travels over a bounded JSON pipe to a disposable process;
originals are never written. The host applies Seatbelt on macOS or bubblewrap plus seccomp on Linux, denies network
and process creation, gives read-only access to the worker/runtime and installed model assets, and kills the process
on cancellation or its 20-second deadline. Without an OS sandbox, photo processing fails closed. The worker preloads
fixed native codecs and then installs import and audit restrictions; it cannot read learner databases or attachments.

The pipeline checks encoded bytes and pixel dimensions, applies EXIF orientation, face/person screening on the whole
original, crop/perspective correction, deskew, local text privacy masking, quality checks and a metadata-free JPEG
no larger than 1,600 pixels / 2 MB. Detector XML hashes and the OpenCV version are pinned in `detectors.json`.
Tesseract is accessed through the fixed `tesserocr` native extension, with no direct ctypes or child process API.
Uncertain OCR tokens become `[?]`. A missing local text privacy pass permits volatile local vision reading, but no
stored derivative or outbound image. Reading never starts a tutoring turn: editable student confirmation is required.

`tesserocr` includes native Tesseract/Leptonica in supported wheels. English traineddata is independent of code:
release perception packs must supply reviewed model assets in `perception_worker/native/tessdata/eng.traineddata`; development
can use an existing OS installation. No traineddata is downloaded at runtime. Without it, the local vision route can
still be offered with volatile-only images. No handwriting recognizer or PDF support is included in this S2 work.

OpenCV wheels contain FFmpeg and platform libraries under LGPL; tesserocr depends on LGPLv3 cysignals. The pinned
package licence files are retained under `licences/`, and dependency reviews record the conditions. Platform releases
must preserve library replacement, include the licence texts and provide corresponding native-library sources and
build information. The ordinary Python metadata SBOM is insufficient to certify those embedded native libraries.
The release compliance gate and signing process must verify them before distribution. `perception-worker.spec`
prepares a separate one-dir artifact from a matching `JANA_OCR_DATA_FILE`; `build-sidecars.sh` keeps it outside the
base installer. Frozen cores require a command supplied by a verified perception-pack loader and otherwise refuse
photo processing. The executable pack uses `ops/perception-pack`, signed by an updater intermediate; model keys cannot authorize code.
Install its folder through Settings → Content → Install from folder. The core stages and verifies every file before
atomic rename, then rechecks signatures/revocations and hashes before every launch. The pack is under
`packs/perception/`, separate from 7B+ tutor models. Invalid, wrong-platform or missing packs keep photo reading off.

Synthetic tests exercise the worker, privacy masking, bounded decoding and capture lifecycle. They do not certify
face/person detection accuracy, printed-formula recognition, confidence calibration or reference-laptop latency.
EVL-12/INP-18/23/29 remain real-device and labelled-fixture acceptance gates. On Windows the worker runs in its own
AppContainer inside a job object (SEC-06, G16; `agent_core.tools.worker.winsandbox`), verified on the Windows CI
runner; where it cannot be applied photo reading stays off. A signed, licence-reviewed traineddata/model pack remains
platform release work; no unsupported platform is silently enabled.
