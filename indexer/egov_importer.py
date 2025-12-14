from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Optional
import xml.etree.ElementTree as ET

from indexer.utils import normalize_text


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_number(value: Optional[str]) -> Optional[int | str]:
    if value is None:
        return None
    value = normalize_text(value)
    if not value:
        return None
    translated = value.translate(str.maketrans({"０": "0", "１": "1", "２": "2", "３": "3", "４": "4", "５": "5", "６": "6", "７": "7", "８": "8", "９": "9"}))
    if translated.isdigit():
        return int(translated)
    return value


def _joined_text(elem: ET.Element) -> str:
    # ネストした要素が混じっても拾えるようにする
    return "".join(elem.itertext())


def find_first_text(element: ET.Element, *names: str) -> Optional[str]:
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
    sentences: List[str] = []
    for elem in elements:
        for sentence_text in elem.findall('.//{*}SentenceText'):
            if sentence_text.text:
                sentences.append(sentence_text.text)
    joined = "".join(sentences)
    return normalize_text(joined)


def parse_item(item_elem: ET.Element) -> Optional[dict]:
    item_no = item_elem.attrib.get("Num") or find_first_text(item_elem, "ItemTitle", "ItemNum")
    text = extract_sentence_texts([item_elem])
    if not text:
        return None
    return {
        "item_no": parse_number(item_no),
        "text": text,
    }


def parse_paragraph(paragraph_elem: ET.Element) -> Optional[dict]:
    paragraph_no = paragraph_elem.attrib.get("Num") or find_first_text(paragraph_elem, "ParagraphNum")
    paragraph_text = extract_sentence_texts(paragraph_elem.findall('./{*}ParagraphSentence'))

    items: List[dict] = []
    for item_elem in paragraph_elem.findall('./{*}Item'):
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


def parse_article(article_elem: ET.Element) -> Optional[dict]:
    article_no = find_first_text(article_elem, "ArticleNum")
    heading = normalize_text(find_first_text(article_elem, "ArticleTitle") or "")

    paragraphs: List[dict] = []
    for paragraph_elem in article_elem.findall('./{*}Paragraph'):
        paragraph = parse_paragraph(paragraph_elem)
        if paragraph:
            paragraphs.append(paragraph)

    if not paragraphs:
        article_text = extract_sentence_texts([article_elem])
        if not article_text:
            return None
        paragraphs.append({"paragraph_no": None, "items": [{"item_no": None, "text": article_text}]})

    return {
        "article_no": normalize_text(article_no or ""),
        "heading": heading,
        "paragraphs": paragraphs,
    }


def parse_law(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    law_id = (
        find_first_text(root, "LawId", "LawID", "LawNum")
        or root.attrib.get("LawID")
        or root.attrib.get("Id")
        or xml_path.stem
    )
    law_name = find_first_text(root, "LawTitle", "LawName") or law_id
    enforce_date = find_first_text(root, "EnactDate", "AmendmentDate", "PromulgationDate")
    year_enforced = enforce_date[:4] if enforce_date and len(enforce_date) >= 4 else None

    articles: List[dict] = []
    for article_elem in root.findall('.//{*}Article'):
        article = parse_article(article_elem)
        if article:
            articles.append(article)

    return {
        "law_id": normalize_text(law_id),
        "law_name": normalize_text(law_name),
        "law_aliases": [],
        "articles": articles,
    } | ({"year_enforced": year_enforced} if year_enforced else {})


def import_directory(xml_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for xml_path in sorted(xml_dir.glob("*.xml")):
        law = parse_law(xml_path)
        output_path = output_dir / f"{law['law_id']}.json"
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(law, fh, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import e-Gov law XML files into JSON corpus format")
    parser.add_argument("--xml-dir", type=Path, required=True, help="Directory containing downloaded e-Gov law XML files")
    parser.add_argument("--output", type=Path, required=True, help="Directory to store converted JSON files")
    args = parser.parse_args()

    import_directory(args.xml_dir, args.output)


if __name__ == "__main__":
    main()
