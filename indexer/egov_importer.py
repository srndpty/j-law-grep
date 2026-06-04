from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional
    tqdm = None

from indexer.manifest import write_manifest
from indexer.schema import (
    WARN_APPENDIX_SKIPPED,
    ParseWarning,
    validate_law_document,
    write_warnings_jsonl,
)
from indexer.utils import normalize_text

MAX_CORPUS_FILENAME_STEM = 64
WARNINGS_FILENAME = "import_warnings.jsonl"

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# Appendix/table containers the converter does not turn into searchable records.
APPENDIX_TABLE_TAGS = {"AppdxTable"}
APPENDIX_OTHER_TAGS = {"Appdx", "AppdxStyle", "AppdxFig", "AppdxFormat", "AppdxNote"}


def normalize_article_no(num_attr: str | None) -> str:
    """Turn an e-Gov Article ``Num`` attribute into a display article number.

    e-Gov encodes branch articles (第2条の2) as ``Num="2_2"``; ``:`` is also
    seen. Join the parts with ``の`` so ``2_2`` -> ``2の2`` and ``2`` -> ``2``.
    """
    if not num_attr:
        return ""
    value = normalize_text(num_attr).translate(_FULLWIDTH_DIGITS)
    parts = [part for part in re.split(r"[_:]", value) if part]
    return "の".join(parts)


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_number(value: str | None) -> int | str | None:
    if value is None:
        return None
    value = normalize_text(value)
    if not value:
        return None
    translated = value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if translated.isdigit():
        return int(translated)
    return value


def _joined_text(elem: ET.Element) -> str:
    # ネストした要素が混じっても拾えるようにする
    return "".join(elem.itertext())


def find_first_text(element: ET.Element, *names: str) -> str | None:
    # 1) 直下優先（従来互換）
    for child in element:
        if local_name(child.tag) in names:
            text = _joined_text(child)
            if text and text.strip():
                return text

    # 2) 子孫まで探索（取りこぼし対策）
    for node in element.iter():
        if local_name(node.tag) in names:
            text = _joined_text(node)
            if text and text.strip():
                return text
    return None


def extract_sentence_texts(elements: Iterable[ET.Element]) -> str:
    sentences: list[str] = []
    for elem in elements:
        # Prefer <Sentence> nodes and use itertext() so nested markup (Ruby,
        # Sub/Sup, etc.) and tail text are not dropped. Fall back to
        # <SentenceText> only when no <Sentence> exists in the subtree.
        sentence_nodes = [node for node in elem.iter() if local_name(node.tag) == "Sentence"]
        if sentence_nodes:
            for node in sentence_nodes:
                sentences.append("".join(node.itertext()))
        else:
            for node in elem.iter():
                if local_name(node.tag) == "SentenceText":
                    sentences.append("".join(node.itertext()))
    joined = "".join(sentences)
    return normalize_text(joined)


def parse_item(item_elem: ET.Element) -> dict | None:
    item_no = item_elem.attrib.get("Num") or find_first_text(item_elem, "ItemTitle", "ItemNum")
    text = extract_sentence_texts([item_elem])
    if not text:
        return None
    return {
        "item_no": parse_number(item_no),
        "text": text,
    }


def parse_paragraph(paragraph_elem: ET.Element) -> dict | None:
    paragraph_no = paragraph_elem.attrib.get("Num") or find_first_text(
        paragraph_elem, "ParagraphNum"
    )
    paragraph_text = extract_sentence_texts(paragraph_elem.findall("./{*}ParagraphSentence"))

    items: list[dict] = []
    for item_elem in paragraph_elem.findall("./{*}Item"):
        item = parse_item(item_elem)
        if item:
            items.append(item)

    if items:
        if paragraph_text:
            items.insert(0, {"item_no": None, "text": paragraph_text})
    elif paragraph_text:
        items.append({"item_no": None, "text": paragraph_text})

    if not items:
        return None

    return {
        "paragraph_no": parse_number(paragraph_no),
        "items": items,
    }


def parse_article(article_elem: ET.Element) -> dict | None:
    # e-Gov carries the article number in the Num attribute (e.g. Num="709",
    # Num="2_2" for 第2条の2). Older code only looked for an <ArticleNum>
    # element, which does not exist in e-Gov XML, leaving article_no empty.
    article_no = normalize_article_no(article_elem.attrib.get("Num")) or normalize_text(
        find_first_text(article_elem, "ArticleNum", "ArticleTitle") or ""
    )
    heading = normalize_text(find_first_text(article_elem, "ArticleTitle") or "")

    paragraphs: list[dict] = []
    for paragraph_elem in article_elem.findall("./{*}Paragraph"):
        paragraph = parse_paragraph(paragraph_elem)
        if paragraph:
            paragraphs.append(paragraph)

    if not paragraphs:
        article_text = extract_sentence_texts([article_elem])
        if not article_text:
            return None
        paragraphs.append(
            {"paragraph_no": None, "items": [{"item_no": None, "text": article_text}]}
        )

    return {
        "article_no": normalize_text(article_no or ""),
        "heading": heading,
        "paragraphs": paragraphs,
    }


def parse_suppl_provisions(root: ET.Element) -> list[dict]:
    articles: list[dict] = []
    for provision_index, provision in enumerate(
        (node for node in root.iter() if local_name(node.tag) == "SupplProvision"), start=1
    ):
        article_elems = [node for node in provision.iter() if local_name(node.tag) == "Article"]
        for article_index, article_elem in enumerate(article_elems, start=1):
            article = parse_article(article_elem)
            if article:
                article_no = article["article_no"] or str(article_index)
                article["article_no"] = f"附則{provision_index}-{article_no}"
                article["heading"] = article.get("heading") or "附則"
                articles.append(article)

        direct_paragraphs = [child for child in provision if local_name(child.tag) == "Paragraph"]
        for paragraph_index, paragraph_elem in enumerate(direct_paragraphs, start=1):
            paragraph = parse_paragraph(paragraph_elem)
            if not paragraph:
                continue
            article_no = normalize_text(
                paragraph_elem.attrib.get("Num")
                or find_first_text(paragraph_elem, "ParagraphNum")
                or ""
            ) or str(paragraph_index)
            articles.append(
                {
                    "article_no": f"附則{provision_index}-{article_no}",
                    "heading": "附則",
                    "paragraphs": [paragraph],
                }
            )
        if not direct_paragraphs and not article_elems:
            text = extract_sentence_texts([provision])
            if text:
                articles.append(
                    {
                        "article_no": f"附則{provision_index}-1",
                        "heading": "附則",
                        "paragraphs": [
                            {"paragraph_no": None, "items": [{"item_no": None, "text": text}]}
                        ],
                    }
                )
    return articles


def parse_appendix_tables(root: ET.Element) -> list[dict]:
    articles: list[dict] = []
    for index, node in enumerate(
        (elem for elem in root.iter() if local_name(elem.tag) in APPENDIX_TABLE_TAGS), start=1
    ):
        text = normalize_text(_joined_text(node))
        if not text:
            continue
        title = normalize_text(find_first_text(node, "AppdxTableTitle", "RelatedArticleNum") or "")
        articles.append(
            {
                "article_no": f"別表{index}",
                "heading": title or f"別表{index}",
                "paragraphs": [{"paragraph_no": None, "items": [{"item_no": None, "text": text}]}],
            }
        )
    return articles


def collect_structural_warnings(root: ET.Element, law_id: str) -> list[ParseWarning]:
    """Flag content the converter drops: appendix tables, figures, and
    supplementary provisions whose body is paragraphs (not articles)."""
    warnings: list[ParseWarning] = []
    for node in root.iter():
        name = local_name(node.tag)
        if name in APPENDIX_TABLE_TAGS:
            continue
        elif name in APPENDIX_OTHER_TAGS:
            warnings.append(ParseWarning(WARN_APPENDIX_SKIPPED, law_id, f"{name} not converted"))
    for node in root.iter():
        if local_name(node.tag) != "SupplProvision":
            continue
        continue
    return warnings


def parse_law_tree(root: ET.Element, fallback_stem: str) -> dict:
    law_id = (
        find_first_text(root, "LawId", "LawID", "LawNum")
        or root.attrib.get("LawID")
        or root.attrib.get("Id")
        or fallback_stem
    )
    law_name = find_first_text(root, "LawTitle", "LawName") or law_id
    enforce_date = find_first_text(root, "EnactDate", "AmendmentDate", "PromulgationDate")
    year_enforced = enforce_date[:4] if enforce_date and len(enforce_date) >= 4 else None

    articles: list[dict] = []
    suppl_article_ids = {
        id(article_elem)
        for provision in root.iter()
        if local_name(provision.tag) == "SupplProvision"
        for article_elem in provision.iter()
        if local_name(article_elem.tag) == "Article"
    }
    for article_elem in root.findall(".//{*}Article"):
        if id(article_elem) in suppl_article_ids:
            continue
        article = parse_article(article_elem)
        if article:
            articles.append(article)

    articles.extend(parse_suppl_provisions(root))
    articles.extend(parse_appendix_tables(root))

    # Fallback: some early-era or appendix-only laws have no Article nodes.
    # Convert top-level paragraphs into pseudo articles so the corpus is not empty.
    if not articles:
        for idx, paragraph_elem in enumerate(root.findall(".//{*}LawBody//{*}Paragraph"), start=1):
            paragraph = parse_paragraph(paragraph_elem)
            if not paragraph:
                continue
            article_no = normalize_text(
                paragraph_elem.attrib.get("Num")
                or find_first_text(paragraph_elem, "ParagraphNum")
                or ""
            ) or str(idx)
            articles.append(
                {
                    "article_no": article_no,
                    "heading": "",
                    "paragraphs": [paragraph],
                }
            )

    return {
        "law_id": normalize_text(law_id),
        "law_name": normalize_text(law_name),
        "law_aliases": [],
        "articles": articles,
    } | ({"year_enforced": year_enforced} if year_enforced else {})


def parse_law(xml_path: Path) -> dict:
    root = ET.parse(xml_path).getroot()
    return parse_law_tree(root, xml_path.stem)


def stable_output_stem(law: dict) -> str:
    raw_id = normalize_text(str(law.get("law_id", "")))
    if (
        raw_id
        and len(raw_id) <= MAX_CORPUS_FILENAME_STEM
        and all(ch not in raw_id for ch in '\\/:*?"<>|')
    ):
        return raw_id
    seed = "|".join(
        [
            raw_id,
            normalize_text(str(law.get("law_name", ""))),
            normalize_text(str(law.get("year_enforced", ""))),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def import_directory(xml_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    xml_paths = sorted(xml_dir.rglob("*.xml"))
    if not xml_paths:
        print(f"No XML files found under {xml_dir}", file=sys.stderr)
        return

    iterator = tqdm(xml_paths, desc="Converting", unit="file") if tqdm else xml_paths
    count = 0
    warnings: list[ParseWarning] = []
    for xml_path in iterator:
        root = ET.parse(xml_path).getroot()
        law = parse_law_tree(root, xml_path.stem)
        warnings.extend(collect_structural_warnings(root, law["law_id"]))
        warnings.extend(validate_law_document(law))
        output_path = output_dir / f"{stable_output_stem(law)}.json"
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(law, fh, ensure_ascii=False, indent=2)
        count += 1
        if not tqdm and count % 100 == 0:
            print(f"Converted {count} / {len(xml_paths)}", file=sys.stderr)

    manifest_path = write_manifest(output_dir, source="e-gov-xml")
    warnings_path = output_dir / WARNINGS_FILENAME
    written = write_warnings_jsonl(warnings_path, warnings)
    print(f"Converted {count} XML files under {xml_dir} -> {output_dir}")
    print(f"Wrote corpus manifest: {manifest_path}")
    if written:
        summary: dict[str, int] = {}
        for warning in warnings:
            summary[warning.code] = summary.get(warning.code, 0) + 1
        ordered = ", ".join(f"{code}={n}" for code, n in sorted(summary.items()))
        print(f"Wrote {written} parse warnings -> {warnings_path} ({ordered})", file=sys.stderr)
    else:
        print("No parse warnings.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import e-Gov law XML files into JSON corpus format"
    )
    parser.add_argument(
        "--xml-dir",
        type=Path,
        required=True,
        help="Directory containing downloaded e-Gov law XML files",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Directory to store converted JSON files"
    )
    args = parser.parse_args()

    import_directory(args.xml_dir, args.output)


if __name__ == "__main__":
    main()
