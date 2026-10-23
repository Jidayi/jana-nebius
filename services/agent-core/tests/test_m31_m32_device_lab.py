"""Named voice acceptance tests that only the device lab can run (G116, G117): each needs a signed English speech pack
with real standard models, the reference laptops (EVL-14) and, for some, consented adult recordings. Until those
inputs exist each test skips and names exactly what it waits for; the software paths they measure are covered by the
other M31 and M32 tests with synthetic audio and a scripted speech endpoint."""

import os

import pytest

PACK = "a signed English speech pack (sp.en.*, VOC-03) with the real standard models of TABLE VOC-03a"
LAB = "the device lab's measurement files (JANA_DEVLAB_RESULTS, one <laptop>.json per reference laptop, EVL-14)"


def _waiting(what: str) -> None:
    """Skip with the inputs this measurement waits for; the reason is the same with or without a lab folder until the
    lab's voice record format and its budget keys exist."""
    lab = os.environ.get("JANA_DEVLAB_RESULTS")
    where = f"no voice runs in {lab}" if lab else "JANA_DEVLAB_RESULTS is not set"
    pytest.skip(f"device lab ({where}): needs {what}")


# --- M31 ------------------------------------------------------------------------------------------------------------


def voc01_offline_round_trip() -> None:
    _waiting(f"{PACK}, the mid and high reference laptops with every network interface but loopback disabled, a "
             "scripted English session (listen, transcribe, tutor turn, speak), read-aloud on the content-only, low, "
             f"mid and high laptops and a dictated utterance on each laptop with a pack; results in {LAB}")  # fmt: skip


def voc18_read_aloud_offline() -> None:
    _waiting(f"networking disabled on the content-only laptop (OS synthesiser with an installed English voice) and on "
             f"the low and mid laptops with {PACK}; results in {LAB}")  # fmt: skip


def voc18_first_audio_budget() -> None:
    _waiting(f"the 100-utterance read-aloud script timed on the low, mid and high laptops with {PACK} (p50 and p90 "
             f"time to first audio per class, VOC-18); results in {LAB}")  # fmt: skip


def voc09_caption_drift() -> None:
    _waiting(f"real synthesised speech from {PACK} with word timings measured against playback at each sentence end "
             f"(VOC-09); results in {LAB}")  # fmt: skip


def voc17_screen_reader_ducking() -> None:
    _waiting("each OS screen reader (Narrator, VoiceOver, Orca) running on a reference laptop while tutor speech "
             "and read-aloud play, with the announcement and playback levels recorded (VOC-17); results in "
             f"{LAB}")  # fmt: skip


# --- M32 ------------------------------------------------------------------------------------------------------------


def voc03_memory_budget() -> None:
    _waiting(f"peak resident memory of the voice sidecar with {PACK} plus the tutor model during a voice turn on each "
             f"reference laptop, against the voice_memory_headroom_gb key (VOC-03); results in {LAB}")  # fmt: skip


def voc36_heard_text_accuracy() -> None:
    _waiting(f"barge-in fixtures played through {PACK}'s synthesiser with the audio actually played recorded, so the "
             f"persisted heard text can be compared word by word (VOC-36); results in {LAB}")  # fmt: skip


def voc05_false_cutoff_rate() -> None:
    _waiting("the thinking-pause set of consented adult recordings (VOC-21; no student audio, D56) played into the "
             f"mid and high laptops with {PACK} and Smart Turn; results in {LAB}")  # fmt: skip


def voc11_barge_in_latency() -> None:
    _waiting(f"playback stop times from the stop key and from spoken barge-in onset on the mid and high laptops with "
             f"{PACK}, measured at the audio output (VOC-11); results in {LAB}")  # fmt: skip


def voc13_latency_budget() -> None:
    _waiting(f"the 100-turn voice script with fixtures of known speech end on the mid and high laptops with {PACK}, "
             f"timed from speech end to first accepted audio and to UI playback start (VOC-13, VOC-22); results in "
             f"{LAB}")  # fmt: skip


def voc21_voice_gates() -> None:
    _waiting(f"the frozen, hash-locked voice sets of VOC-21 (licensed or consented adult speech, EVL-18, EVL-24), "
             f"listener panels for each offered voice and a voice suite in evals/suites.toml, run through {PACK} on "
             f"the reference laptops; results in {LAB}")  # fmt: skip


def voc44_voice_scenarios() -> None:
    _waiting(f"the voice scenario suite of VOC-44 run with the real sidecar and {PACK}, the OS synthesiser of each "
             f"platform and recorded audio fixtures (EVL-03); results in {LAB}")  # fmt: skip


def jrn15_voice_session() -> None:
    _waiting(f"a whole voice session (JRN-15) walked on the mid and high reference laptops with {PACK} and a "
             f"microphone; results in {LAB}")  # fmt: skip


def jrn15_failure_branches() -> None:
    _waiting(f"the JRN-15 failure branches (microphone refused or lost, sidecar crash, pack removed, low power) "
             f"walked on a reference laptop with {PACK}; results in {LAB}")  # fmt: skip
