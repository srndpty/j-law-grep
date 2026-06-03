"""Lightweight, dependency-free validation for converted corpus JSON.

The e-Gov importer emits documents shaped like::

    {
      "law_id": str,
      "law_name": str,
      "law_aliases": [str, ...],
      "year_enforced": str | None,
      "articles": [
        {
          "article_no": str,
          "heading": str,
          "paragraphs": [
            {"paragraph_no": int | str | None,
             "items": [{"item_no": int | str | None, "text": str}, ...]}
          ]
        }
      ]
    }

`validate_law_document` walks that shape and returns structured
:class:`ParseWarning` records instead of raising, so a flaky source law never
aborts a whole-corpus conversion. Warnings are written as JSONL by the importer
so "I thought it imported but it didn't" failures are visible after the fact.

We deliberately avoid pydantic here to keep the indexer dependency-free; the
shape is small and stable enough for explicit checks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

# Warning codes (kept as module constants so callers can filter/aggregate).
WARN_EMPTY_LAW_ID = "empty_law_id"
WARN_EMPTY_LAW_NAME = "empty_law_name"
WARN_EMPTY_LAW = "empty_law"
WARN_MISSING_ARTICLE_NO = "missing_article_no"
WARN_SHORT_CONTENT = "short_content"
WARN_UNSUPPORTED_ITEM_NO = "unsupported_item_no"
WARN_LOST_TABLE = "lost_table"
WARN_APPENDIX_SKIPPED = "appendix_skipped"

# Minimum sensible article body length; shorter usually means a parse miss.
MIN_ARTICLE_CONTENT_CHARS = 2

# Item numbers we can render meaningfully: arabic digits, kanji numerals and
# the iroha sequence used for 号 (e.g. 一 / 第一号 / イ). Anything else is kept
# as-is but flagged so the importer surface area is visible.
_KANJI_NUMERAL_CHARS = set("〇零一二三四五六七八九十百千万")
_IROHA_CHARS = set(
    "イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセス"
)


def is_recognized_item_no(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    # Strip the optional 第…号 wrapper before inspecting the core token.
    core = text.removeprefix("第").removesuffix("号")
    if not core:
        return True
    if core.isdigit():
        return True
    chars = set(core)
    return chars <= _KANJI_NUMERAL_CHARS or chars <= _IROHA_CHARS


@dataclass
class ParseWarning:
    code: str
    law_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _article_text_length(article: dict) -> int:
    total = 0
    for paragraph in article.get("paragraphs", []) or []:
        for item in paragraph.get("items", []) or []:
            total += len((item.get("text") or "").strip())
    return total


def validate_law_document(doc: dict) -> list[ParseWarning]:
    """Return warnings describing structural problems in a converted law."""
    law_id = str(doc.get("law_id") or "").strip()
    law_name = str(doc.get("law_name") or "").strip()
    warnings: list[ParseWarning] = []
    label = law_id or law_name or "<unknown>"

    if not law_id:
        warnings.append(ParseWarning(WARN_EMPTY_LAW_ID, label, "law_id is empty"))
    if not law_name:
        warnings.append(ParseWarning(WARN_EMPTY_LAW_NAME, label, "law_name is empty"))

    articles = doc.get("articles") or []
    if not articles:
        warnings.append(ParseWarning(WARN_EMPTY_LAW, label, "no articles"))
        return warnings

    usable_records = 0
    for index, article in enumerate(articles):
        article_no = str(article.get("article_no") or "").strip()
        heading = str(article.get("heading") or "").strip()
        if not article_no:
            warnings.append(
                ParseWarning(
                    WARN_MISSING_ARTICLE_NO,
                    label,
                    f"article #{index} has empty article_no (heading={heading!r})",
                )
            )
        text_len = _article_text_length(article)
        if text_len == 0:
            continue
        if text_len < MIN_ARTICLE_CONTENT_CHARS:
            warnings.append(
                ParseWarning(
                    WARN_SHORT_CONTENT,
                    label,
                    f"article {article_no or index!r} body is {text_len} chars",
                )
            )
        for paragraph in article.get("paragraphs", []) or []:
            for item in paragraph.get("items", []) or []:
                if (item.get("text") or "").strip():
                    usable_records += 1
                if not is_recognized_item_no(item.get("item_no")):
                    warnings.append(
                        ParseWarning(
                            WARN_UNSUPPORTED_ITEM_NO,
                            label,
                            f"article {article_no or index!r} item_no={item.get('item_no')!r}",
                        )
                    )

    if usable_records == 0:
        warnings.append(ParseWarning(WARN_EMPTY_LAW, label, "no usable text records"))
    return warnings


def write_warnings_jsonl(path: Path, warnings: Iterator[ParseWarning] | list[ParseWarning]) -> int:
    """Write warnings as JSON Lines; return the number written."""
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for warning in warnings:
            fh.write(json.dumps(warning.as_dict(), ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
            count += 1
    return count
