from __future__ import annotations

import re

WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    value = value.replace("\u3000", " ")
    value = WHITESPACE_PATTERN.sub(" ", value)
    return value.strip()
