"""One cloud extraction per disposable, network-denied process; stdout carries only the bounded result."""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

from study_worker import DocumentError, decode


def main() -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (240, 250))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    result: dict[str, Any]
    try:
        line = sys.stdin.buffer.readline(140_000_000)
        if len(line) >= 140_000_000 or not line.endswith(b"\n"):
            raise DocumentError("source_too_large")
        request = json.loads(line)
        data = base64.b64decode(request["data"], validate=True)
        if len(data) > 104857600:
            raise DocumentError("source_too_large")
        if request["kind"] in ("recording_info", "recording_segment"):
            from study_worker.media import decode as media_decode

            maximum = request.get("max_minutes", 120)
            if type(maximum) is not int or not 1 <= maximum <= 120:
                raise DocumentError("source_too_large")
            result = media_decode(
                data,
                request.get("start_ms") if request["kind"] == "recording_segment" else None,
                maximum,
                request.get("duration_ms"),
            )
            sys.stdout.write(json.dumps(result) + "\n")
            return
        limit = request.get("max_units", 300)
        if type(limit) is not int or not 1 <= limit <= 300:
            raise DocumentError("source_too_large")
        units = decode(data, request["kind"], "", limit)
        for unit in units:
            if unit.get("ocr"):
                from perception_worker.image import preprocess  # type: ignore[import-untyped]

                png = decode(data, "raster_" + request["kind"], str(unit["locator"]["page"]))[0]["png"]
                reading = preprocess(base64.b64decode(png))
                if reading.get("refusal"):
                    raise DocumentError("safety_blocked")
                if reading.get("ocr_model_version") is None:
                    raise DocumentError("model_unavailable")
                lines = reading.get("lines", [])
                unit["text"] = (
                    "\n".join(line["text"] for line in lines)
                    if lines
                    and all(line["confidence"] >= 0.85 and not line.get("low_confidence_spans") for line in lines)
                    else ""
                )
        if sum(len(u["text"]) for u in units) > 2_000_000:
            raise DocumentError("source_too_large")
        result = {"units": units}
        if len(json.dumps(result).encode()) > 4_000_000:
            raise DocumentError("source_too_large")
    except DocumentError as error:
        result = {"error": str(error)}
    except Exception:
        result = {"error": "corrupt_source"}
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
