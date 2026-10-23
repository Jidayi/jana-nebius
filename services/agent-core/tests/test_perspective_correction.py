"""INP-17: procedural 30-degree camera projections exercise real rectification and JPEG output.

This is software geometry evidence, not a labelled real-photo/reader/device-quality evaluation.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from perception_worker import image
from PIL import Image


def projected_page(degrees: int) -> tuple[bytes, list[dict[str, float]]]:
    width, height = 600, 800
    page = np.full((height, width, 3), 255, dtype=np.uint8)
    # Known synthetic print baselines lie below the optical centre, so the uncorrected slopes cannot cancel out.
    for y in range(480, 761, 40):
        cv2.putText(page, "SYNTHETIC TEXT BASELINE", (70, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 1)
        cv2.line(page, (70, y), (530, y), (0, 0, 0), 3)
    source = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    theta = np.radians(degrees)
    centered = source - np.array([(width - 1) / 2, (height - 1) / 2])
    z = 1100 - centered[:, 0] * np.sin(theta)
    target = np.column_stack((450 + 900 * centered[:, 0] * np.cos(theta) / z, 550 + 900 * centered[:, 1] / z)).astype(
        np.float32
    )
    projected = cv2.warpPerspective(
        page, cv2.getPerspectiveTransform(source, target), (900, 1100), borderValue=(225, 225, 225)
    )
    encoded = io.BytesIO()
    Image.fromarray(projected).save(encoded, "JPEG", quality=95)
    corners = [{"x": float(x / 899), "y": float(y / 1099)} for x, y in target]
    return encoded.getvalue(), corners


def baseline_angles(pixels: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    lines = cv2.HoughLinesP(cv2.Canny(gray, 50, 150), 1, np.pi / 180, threshold=65, minLineLength=100, maxLineGap=10)
    assert lines is not None
    angles = np.array([((np.degrees(np.arctan2(y2 - y1, x2 - x1)) + 90) % 180) - 90 for x1, y1, x2, y2 in lines[:, 0]])
    angles = angles[np.abs(angles) < 25]
    assert len(angles) >= 8
    return np.abs(angles)


@pytest.mark.parametrize("angle", [30, -30])
def inp17_perspective_correction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, angle: int) -> None:
    monkeypatch.setattr(image, "words", lambda _: None)  # no OCR/model output supplies the geometry result
    raw, corners = projected_page(angle)
    assert float(np.median(baseline_angles(image.decode(raw)))) > 2
    corrected = image.preprocess(raw, corners=corners)
    assert corrected["refusal"] is None
    jpeg = base64.b64decode(corrected["jpeg"])
    residual = baseline_angles(image.decode(jpeg))
    assert float(np.percentile(residual, 95)) <= 2
    # Omitting the projective correction must fail the same residual-angle metric even with normal deskew enabled.
    with monkeypatch.context() as mutation:
        mutation.setattr(image, "rectify", lambda pixels, _corners: pixels)
        unrectified = image.preprocess(raw, corners=corners)
        failed_angles = baseline_angles(image.decode(base64.b64decode(unrectified["jpeg"])))
        assert float(np.percentile(failed_angles, 95)) > 2
    # No image-file path is used by the software pipeline; originals/output above are memory buffers only.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "corners",
    [
        [{"x": 0, "y": 0}] * 3,
        [{"x": 0, "y": 0}] * 4,
        [{"x": -0.1, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
        [{"x": 0, "y": 0}, {"x": 1.1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
        [{"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 1, "y": 0}, {"x": 0, "y": 1}],
        [{"x": float("nan"), "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
    ],
)
def test_invalid_perspective_quads_are_refused_before_warping(corners: list[dict[str, float]]) -> None:
    with pytest.raises(image.ImageRejected, match="validation_failed"):
        image.rectify(np.zeros((100, 100, 3), dtype=np.uint8), corners)
