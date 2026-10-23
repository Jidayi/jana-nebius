"""Server-only media decoding inside the network-denied worker; all source and PCM bytes stay in memory."""

from __future__ import annotations

import base64
import io
import math
import wave
from typing import Any

from study_worker import DocumentError

FORMATS = {"wav", "mp3", "flac", "aac", "ogg", "mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "avi"}
RATE = 16000


def decode(
    data: bytes, start_ms: int | None, max_minutes: int, verified_duration_ms: int | None = None
) -> dict[str, Any]:
    import av  # Installed only on the gateway, not a desktop dependency.

    try:
        with av.open(
            io.BytesIO(data), mode="r", options={"protocol_whitelist": "pipe", "enable_drefs": "0"}
        ) as container:
            if not set(container.format.name.split(",")) & FORMATS or not container.streams.audio:
                raise DocumentError("unsupported_format")
            stream = container.streams.audio[0]
            stream.codec_context.thread_type = "SLICE"
            stream.codec_context.thread_count = 1
            duration = (
                float(stream.duration * stream.time_base)
                if stream.duration is not None
                else container.duration / av.time_base
                if container.duration is not None
                else None
            )
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise DocumentError("unreadable_source")
            duration_ms = math.ceil(duration * 1000)
            origin = float((stream.start_time or 0) * stream.time_base)
            if start_ms is None:
                # Inspect packet timestamps too: a forged short header must not silently truncate the source.
                for count, packet in enumerate(container.demux(stream)):
                    if count > 2_000_000:
                        raise DocumentError("source_too_large")
                    if packet.pts is not None:
                        duration_ms = max(
                            duration_ms,
                            math.ceil(
                                (float((packet.pts + (packet.duration or 0)) * stream.time_base) - origin) * 1000
                            ),
                        )
                    if duration_ms > max_minutes * 60000:
                        raise DocumentError("source_too_large")
            elif verified_duration_ms is not None:
                if type(verified_duration_ms) is not int or not 0 < verified_duration_ms <= max_minutes * 60000:
                    raise DocumentError("source_too_large")
                duration_ms = verified_duration_ms
            if duration_ms > max_minutes * 60000:
                raise DocumentError("source_too_large")
            if start_ms is None:
                return {"duration_ms": duration_ms}
            if type(start_ms) is not int or start_ms < 0 or start_ms >= duration_ms:
                raise DocumentError("invalid_request")
            end_ms = min(duration_ms, start_ms + 60000)
            container.seek(max(0, int((origin + start_ms / 1000 - 1) / stream.time_base)), stream=stream)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
            pcm = bytearray()
            for frame in container.decode(stream):
                if frame.time is None:
                    raise DocumentError("unreadable_source")
                if (frame.time - origin) * 1000 >= end_ms:
                    break
                for audio in resampler.resample(frame):
                    if audio.pts is None:
                        raise DocumentError("unreadable_source")
                    at_ms = (float(audio.pts * audio.time_base) - origin) * 1000
                    first = max(0, round((start_ms - at_ms) * RATE / 1000))
                    last = min(audio.samples, round((end_ms - at_ms) * RATE / 1000))
                    if last > first:
                        pcm.extend(bytes(audio.planes[0])[first * 2 : last * 2])
                    if len(pcm) > 60000 * RATE * 2 // 1000:
                        raise DocumentError("source_too_large")
            if not pcm:
                raise DocumentError("unreadable_source")
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(RATE)
                wav.writeframes(pcm)
            return {
                "duration_ms": duration_ms,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "wav_base64": base64.b64encode(output.getvalue()).decode(),
            }
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("corrupt_source") from None
