from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

FULLWIDTH_DIGITS = str.maketrans({
    "０": "0",
    "１": "1",
    "２": "2",
    "３": "3",
    "４": "4",
    "５": "5",
    "６": "6",
    "７": "7",
    "８": "8",
    "９": "9",
})

KANJI_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
KANJI_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
}


@dataclass
class Citation:
    law_name: Optional[str]
    article_no: Optional[str]
    paragraph_no: Optional[int]
    item_no: Optional[int]


def _kanji_to_int(value: str) -> Optional[int]:
    if not value:
        return None
    total = 0
    current = 0
    for ch in value:
        if ch in KANJI_DIGITS:
            current += KANJI_DIGITS[ch]
        elif ch in KANJI_UNITS:
            if current == 0:
                current = 1
            total += current * KANJI_UNITS[ch]
            current = 0
        else:
            return None
    total += current
    return total


def _normalize_number(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    normalized = value.translate(FULLWIDTH_DIGITS)
    if normalized.isdigit():
        return int(normalized)
    kanji_value = _kanji_to_int(normalized)
    return kanji_value


def parse_citation(text: str) -> Citation:
    normalized = text.translate(FULLWIDTH_DIGITS)
    pattern = re.compile(
        r"(?:(?P<law>[\w\-・（）()\u3000\s\u4e00-\u9fff々〆]+?)\s*)?"
        r"(?:第)?(?P<article>[0-9一二三四五六七八九十百千〇零]+)条"
        r"(?:\s*(?P<paragraph>[0-9一二三四五六七八九十百千〇零]+)項)?"
        r"(?:\s*(?P<item>[0-9一二三四五六七八九十百千〇零]+)号)?"
    )
    match = pattern.search(normalized)
    if not match:
        return Citation(law_name=None, article_no=None, paragraph_no=None, item_no=None)

    law_name = match.group("law")
    if law_name:
        law_name = law_name.strip()

    article_raw = match.group("article")
    paragraph_raw = match.group("paragraph")
    item_raw = match.group("item")

    paragraph_no = _normalize_number(paragraph_raw)
    item_no = _normalize_number(item_raw)

    article_no = article_raw
    if article_raw:
        article_no = article_raw.translate(FULLWIDTH_DIGITS)
        if article_no.isdigit():
            article_no = article_no
        else:
            kanji = _kanji_to_int(article_raw)
            article_no = str(kanji) if kanji is not None else article_raw

    return Citation(
        law_name=law_name,
        article_no=article_no,
        paragraph_no=paragraph_no,
        item_no=item_no,
    )


def citation_key(citation: Citation) -> Optional[str]:
    if not citation.law_name or not citation.article_no:
        return None
    parts = [citation.law_name.strip(), f"{citation.article_no}条"]
    if citation.paragraph_no is not None:
        parts.append(f"{citation.paragraph_no}項")
    if citation.item_no is not None:
        parts.append(f"{citation.item_no}号")
    return " ".join(parts)
