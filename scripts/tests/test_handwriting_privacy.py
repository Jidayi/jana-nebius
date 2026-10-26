"""Document-only corroboration for HOG's handwriting false positives; face refusals stay unconditional."""

from pathlib import Path

import numpy as np
import pytest
from perception_worker import image

FIXTURE = Path(__file__).resolve().parents[2] / "evals/perception/handwriting/synthetic-biology.png"


def test_handwriting_body_false_positive_is_corroborated_only_for_study_documents():
    pixels = image.decode(FIXTURE.read_bytes())
    assert image.contains_person(pixels)
    assert image.text_only_document(pixels)
    assert not image.contains_person(pixels, document=True)
    assert image.preprocess(FIXTURE.read_bytes(), document=True)["privacy_available"]


def test_unexplained_ink_or_missing_ocr_prevents_document_exception(monkeypatch):
    pixels = image.decode(FIXTURE.read_bytes())
    pixels[650:800, 100:300] = 0
    assert not image.text_only_document(pixels)
    monkeypatch.setattr(image, "words", lambda _: None)
    assert not image.text_only_document(image.decode(FIXTURE.read_bytes()))
    assert image.contains_person(image.decode(FIXTURE.read_bytes()), document=True)


def test_a_face_cascade_refusal_is_never_overridden_by_document_text(monkeypatch):
    class Face:
        def empty(self):
            return False

        def detectMultiScale(self, *args, **kwargs):
            return np.array([[20, 20, 100, 100]])

    monkeypatch.setattr(image.cv2, "CascadeClassifier", lambda _: Face())
    monkeypatch.setattr(
        image, "text_only_document", lambda _: pytest.fail("face rejection must precede document proof")
    )
    assert image.contains_person(image.decode(FIXTURE.read_bytes()), document=True)
