"""PRV-29 request-context evidence: closed message shapes and student-photo-only image parts.

This checks actual wire requests. Source auditing separately establishes that no screen-capture producer exists;
this module does not infer image provenance from its pixels or judge model accuracy.
"""

from __future__ import annotations

import base64
import io
from collections import Counter
from typing import Any

from PIL import Image

MESSAGE_FIELDS = {"role", "content", "name", "tool_calls", "tool_call_id", "reasoning_content"}
ROLES = {"system", "user", "assistant", "tool"}


def audit_requests(requests: list[dict[str, Any]], *, max_image_side: int = 2048) -> dict[str, Any]:
    failures: list[str] = []
    roles: Counter[str] = Counter()
    images = 0
    contexts = 0
    for request in requests:
        role = str(request.get("_role", "unknown"))
        roles[role] += 1
        if any(key in request for key in ("screenshot", "screen", "window", "clipboard", "active_window")):
            failures.append("external_context_field")
        messages = request.get("messages")
        if not isinstance(messages, list):
            failures.append("messages_not_records")
            continue
        context_count = 0
        for message in messages:
            if not isinstance(message, dict) or set(message) - MESSAGE_FIELDS or message.get("role") not in ROLES:
                failures.append("message_not_closed_record")
                continue
            content = message.get("content")
            if isinstance(content, str):
                if message["role"] != "system":
                    context_count += content.count("<tutor-context>\n")
                continue
            if content is None and message.get("tool_calls"):
                continue
            if not isinstance(content, list):
                failures.append("content_not_text_or_parts")
                continue
            for part in content:
                if not isinstance(part, dict):
                    failures.append("part_not_record")
                elif part.get("type") == "text" and set(part) == {"type", "text"} and isinstance(part["text"], str):
                    continue
                elif (
                    part.get("type") == "image_url"
                    and set(part) == {"type", "image_url"}
                    and role == "vision"
                    and message["role"] == "user"
                ):
                    image = part["image_url"]
                    try:
                        if not isinstance(image, dict) or set(image) != {"url"}:
                            raise ValueError("image fields")
                        prefix, data = image["url"].split(",", 1)
                        if prefix != "data:image/jpeg;base64" or len(data) > 4_000_000:
                            raise ValueError("image source")
                        with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as picture:
                            if (
                                picture.format != "JPEG"
                                or max(picture.size) > max_image_side
                                or picture.getexif()
                                or picture.info.get("icc_profile")
                            ):
                                raise ValueError("image derivative")
                        images += 1
                    except (ValueError, TypeError, KeyError, OSError, Image.DecompressionBombError):
                        failures.append("image_not_safe_student_capture")
                else:
                    failures.append("part_not_explicit_student_image_or_text")
        if context_count > 1:
            failures.append("duplicate_tutor_context")
        contexts += context_count
    return {
        "requests": len(requests),
        "roles": dict(sorted(roles.items())),
        "student_images": images,
        "tutor_contexts": contexts,
        "failures": sorted(set(failures)),
    }
