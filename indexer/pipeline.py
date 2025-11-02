from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from backend.search.citation import Citation, citation_key


@dataclass
class IndexRecord:
    law_id: str
    law_name: str
    law_aliases: List[str]
    article_no: str
    paragraph_no: Optional[int]
    item_no: Optional[int]
    heading: str
    content: str
    content_plain: str
    citation: Citation
    year_enforced: Optional[str]
    path: str
    url: str
    blocks: List[dict]


WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    value = value.replace("\u3000", " ")
    value = WHITESPACE_PATTERN.sub(" ", value)
    return value.strip()


def load_documents(input_dir: Path) -> Iterable[dict]:
    for path in sorted(input_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            yield json.load(fh)


def collect_records(input_dir: Path) -> List[IndexRecord]:
    records: List[IndexRecord] = []
    for doc in load_documents(input_dir):
        law_id = doc["law_id"]
        law_name = doc["law_name"]
        law_aliases = doc.get("law_aliases", [])
        year_enforced = doc.get("year_enforced")
        for article in doc.get("articles", []):
            article_no = str(article["article_no"])
            heading = normalize_text(article.get("heading", ""))
            paragraphs = article.get("paragraphs", [])
            if not paragraphs:
                paragraphs = [
                    {
                        "paragraph_no": None,
                        "items": [
                            {
                                "item_no": None,
                                "text": article.get("text", ""),
                            }
                        ],
                    }
                ]
            for paragraph in paragraphs:
                paragraph_no = paragraph.get("paragraph_no")
                items = paragraph.get("items", [])
                if not items:
                    items = [
                        {
                            "item_no": None,
                            "text": paragraph.get("text", ""),
                        }
                    ]
                for item in items:
                    text = normalize_text(item.get("text", ""))
                    if not text:
                        continue
                    item_no = item.get("item_no")
                    citation = Citation(
                        law_name=law_name,
                        article_no=article_no,
                        paragraph_no=paragraph_no,
                        item_no=item_no,
                    )
                    blocks = [
                        {
                            "kind": "text",
                            "html": text,
                        }
                    ]
                    path = f"{law_name}/{article_no}"
                    url = f"/l/{law_id}/a/{article_no}"
                    if paragraph_no:
                        url += f"/{paragraph_no}"
                    if item_no:
                        url += f"/{item_no}"
                    records.append(
                        IndexRecord(
                            law_id=law_id,
                            law_name=law_name,
                            law_aliases=law_aliases,
                            article_no=article_no,
                            paragraph_no=paragraph_no,
                            item_no=item_no,
                            heading=heading,
                            content=text,
                            content_plain=text,
                            citation=citation,
                            year_enforced=year_enforced,
                            path=path,
                            url=url,
                            blocks=blocks,
                        )
                    )
    return records


def to_index_actions(records: Iterable[IndexRecord]) -> List[dict]:
    actions: List[dict] = []
    for record in records:
        citation = citation_key(record.citation)
        doc = {
            "law_id": record.law_id,
            "law_name": record.law_name,
            "law_aliases": record.law_aliases,
            "article_no": record.article_no,
            "paragraph_no": record.paragraph_no,
            "item_no": record.item_no,
            "citation_key": citation,
            "heading": record.heading,
            "content": record.content,
            "content_plain": record.content_plain,
            "year_enforced": record.year_enforced,
            "path": record.path,
            "url": record.url,
            "line": 0,
            "blocks": record.blocks,
        }
        doc_id = f"{record.law_id}-{record.article_no}-{record.paragraph_no or 0}-{record.item_no or 0}"
        actions.append({"_id": doc_id, "_source": doc})
    return actions
