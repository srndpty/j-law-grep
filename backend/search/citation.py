from __future__ import annotations

import re
from dataclasses import dataclass

FULLWIDTH_DIGITS = str.maketrans(
    {
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
    }
)

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
LAW_SUFFIX_TOKENS = {"法", "令", "規則", "条例", "省令", "府令", "庁令"}
LAW_SUFFIXES = tuple(LAW_SUFFIX_TOKENS)
NUMBER_TOKEN = r"[0-9一二三四五六七八九十百千〇零]+"

# Characters that, on their own, never make a real law name. The optional law
# group in the citation pattern is greedy and would otherwise swallow the 第
# prefix or the leading digits of an article number (e.g. "第2条の2" -> law="第",
# "709条" -> law="7" / article="09"). When the captured law consists solely of
# these, we re-parse the citation as having no law name so the full article is
# recovered and no bogus law filter is applied.
_NUMERIC_LAW_CHARS = set("0123456789") | set(KANJI_DIGITS) | set(KANJI_UNITS) | set("第の_:ー 　")

# Citation core without the law group, used to re-parse when the captured law is
# numeric noise so the full article (and any leading 第) is recovered.
_CITATION_PATTERN_NO_LAW = re.compile(
    rf"(?:第)?(?P<article>{NUMBER_TOKEN}(?:[_:の]{NUMBER_TOKEN})*)条"
    rf"(?:の(?P<branch_after>{NUMBER_TOKEN}))?"
    rf"(?:\s*(?P<paragraph>{NUMBER_TOKEN})項)?"
    rf"(?:\s*(?P<item>{NUMBER_TOKEN})号)?"
)


def _is_numeric_law(name: str) -> bool:
    """True when the captured law name is only 第/digits/separators (not a real law)."""
    return all(ch in _NUMERIC_LAW_CHARS for ch in name)


@dataclass
class Citation:
    law_name: str | None
    article_no: str | None
    paragraph_no: int | None
    item_no: int | None


@dataclass
class ParsedCitation:
    citation: Citation
    matched_text: str
    residual_query: str


EMPTY_CITATION = Citation(law_name=None, article_no=None, paragraph_no=None, item_no=None)


def _kanji_to_int(value: str) -> int | None:
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


def _normalize_number(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.translate(FULLWIDTH_DIGITS)
    if normalized.isdigit():
        return int(normalized)
    kanji_value = _kanji_to_int(normalized)
    return kanji_value


def _normalize_article_no(article_raw: str | None, branch_raw: str | None = None) -> str | None:
    if not article_raw:
        return None
    normalized = article_raw.translate(FULLWIDTH_DIGITS)
    parts = [part for part in re.split(r"[_:の]", normalized) if part]
    if branch_raw:
        parts.extend(
            part for part in re.split(r"[_:の]", branch_raw.translate(FULLWIDTH_DIGITS)) if part
        )

    normalized_parts: list[str] = []
    for part in parts:
        if part.isdigit():
            normalized_parts.append(part)
            continue
        kanji = _kanji_to_int(part)
        normalized_parts.append(str(kanji) if kanji is not None else part)
    return "の".join(normalized_parts)


def parse_citation_query(text: str) -> ParsedCitation:
    normalized = text.translate(FULLWIDTH_DIGITS)
    pattern = re.compile(
        r"(?:(?P<law>[\w\-・（）()\u3000\s\u4e00-\u9fff々〆]+?)\s*)?"
        rf"(?:第)?(?P<article>{NUMBER_TOKEN}(?:[_:の]{NUMBER_TOKEN})*)条"
        rf"(?:の(?P<branch_after>{NUMBER_TOKEN}))?"
        rf"(?:\s*(?P<paragraph>{NUMBER_TOKEN})項)?"
        rf"(?:\s*(?P<item>{NUMBER_TOKEN})号)?"
    )
    match = pattern.search(normalized)
    if not match:
        return ParsedCitation(citation=EMPTY_CITATION, matched_text="", residual_query=text.strip())

    law_name = match.group("law")
    residual_prefix = normalized[: match.start()].strip()
    if law_name:
        law_name = law_name.strip()
        law_parts = law_name.split()
        if len(law_parts) > 1:
            last_part = law_parts[-1]
            if last_part in LAW_SUFFIX_TOKENS or (
                len(last_part) > 2 and last_part.endswith(LAW_SUFFIXES)
            ):
                law_name = "".join(law_parts)
            else:
                residual_prefix = " ".join(
                    part for part in [residual_prefix, *law_parts[:-1]] if part
                )
                law_name = last_part

    if law_name and _is_numeric_law(law_name):
        # The greedy law group swallowed the 第 prefix or the article's leading
        # digits (e.g. "第2条の2" -> law="第", "709条" -> law="7"). Re-parse the
        # citation core only, so the full article is captured and no bogus law
        # filter is fabricated; text before the citation stays in the residual.
        no_law = _CITATION_PATTERN_NO_LAW.search(normalized)
        if no_law is not None:
            match = no_law
            law_name = None
            residual_prefix = normalized[: match.start()].strip()

    article_raw = match.group("article")
    branch_after_raw = match.group("branch_after")
    paragraph_raw = match.group("paragraph")
    item_raw = match.group("item")

    paragraph_no = _normalize_number(paragraph_raw)
    item_no = _normalize_number(item_raw)

    article_no = _normalize_article_no(article_raw, branch_after_raw)

    citation = Citation(
        law_name=law_name,
        article_no=article_no,
        paragraph_no=paragraph_no,
        item_no=item_no,
    )
    residual_query = " ".join(
        part.strip() for part in (residual_prefix, normalized[match.end() :]) if part.strip()
    )
    return ParsedCitation(
        citation=citation,
        matched_text=normalized[match.start() : match.end()].strip(),
        residual_query=residual_query,
    )


def parse_citation(text: str) -> Citation:
    return parse_citation_query(text).citation


def citation_key(citation: Citation) -> str | None:
    if not citation.law_name or not citation.article_no:
        return None
    parts = [citation.law_name.strip(), f"{citation.article_no}条"]
    if citation.paragraph_no is not None:
        parts.append(f"{citation.paragraph_no}項")
    if citation.item_no is not None:
        parts.append(f"{citation.item_no}号")
    return " ".join(parts)
