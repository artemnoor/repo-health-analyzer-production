"""Bounded redaction shared by process, provider and persistence boundaries."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Any

_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|bearer|password|secret|token|credential)", re.I)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")


def redact_text(value: str, *, limit: int = 4096) -> str:
    """Remove obvious secrets and local paths before text becomes evidence/logs."""
    text = value[: max(0, limit)]
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+", r"\1=<redacted>", text)
    return "<path>" if _ABSOLUTE_PATH.match(text.strip()) else text


def redact_mapping(value: Mapping[str, Any], *, depth: int = 0, max_items: int = 128) -> dict[str, Any]:
    if depth > 4:
        return {"_redacted": "depth_limit"}
    result: dict[str, Any] = {}
    for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0]))[:max_items]:
        key = str(raw_key)[:128]
        if _SECRET_KEY.search(key):
            result[key] = "<redacted>"
        elif isinstance(raw_value, Mapping):
            result[key] = redact_mapping(raw_value, depth=depth + 1, max_items=max_items)
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
            result[key] = [
                redact_mapping(item, depth=depth + 1, max_items=max_items)
                if isinstance(item, Mapping)
                else redact_text(str(item), limit=512)
                for item in list(raw_value)[:max_items]
            ]
        elif isinstance(raw_value, str):
            result[key] = redact_text(raw_value, limit=512)
        elif raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
        else:
            result[key] = str(raw_value)[:512]
    return result


def digest(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()


def relative_path(path: str) -> str | None:
    normalized = path.replace("\\", "/").strip().lstrip("./")
    if not normalized or normalized.startswith("/") or ".." in PurePath(normalized).parts:
        return None
    return normalized[:4096]


__all__ = ["digest", "redact_mapping", "redact_text", "relative_path"]
