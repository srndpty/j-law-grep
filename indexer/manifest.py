from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from indexer.utils import normalize_text

MANIFEST_FILENAME = "manifest.json"
CORPUS_SCHEMA_VERSION = 2


def iter_corpus_json_paths(input_dir: Path) -> Iterator[Path]:
    for path in sorted(input_dir.glob("*.json")):
        if path.name == MANIFEST_FILENAME:
            continue
        if path.name.startswith("_"):
            continue
        yield path


def document_stats(doc: dict) -> tuple[int, int]:
    if doc.get("source_type") == "diet":
        speeches = doc.get("speeches", []) or []
        return 1, sum(1 for speech in speeches if normalize_text(speech.get("text", "")))

    if doc.get("source_type") == "shuisho":
        # 「article」は質問本文 / 答弁本文の 2 部、record は段落数。
        bodies = [doc.get(kind) for kind in ("question", "answer")]
        present = [body for body in bodies if isinstance(body, dict)]
        record_count = sum(
            1
            for body in present
            for paragraph in body.get("paragraphs", []) or []
            if normalize_text(str(paragraph or ""))
        )
        return len(present), record_count

    article_count = 0
    record_count = 0
    for article in doc.get("articles", []):
        article_count += 1
        paragraphs = article.get("paragraphs", [])
        if not paragraphs:
            record_count += 1 if normalize_text(article.get("text", "")) else 0
            continue
        for paragraph in paragraphs:
            items = paragraph.get("items", [])
            if not items:
                record_count += 1 if normalize_text(paragraph.get("text", "")) else 0
                continue
            record_count += sum(1 for item in items if normalize_text(item.get("text", "")))
    return article_count, record_count


def corpus_digest(paths: Iterable[Path]) -> str:
    hasher = hashlib.sha256()
    for path in paths:
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def build_manifest(input_dir: Path, source: str = "local") -> dict:
    paths = list(iter_corpus_json_paths(input_dir))
    law_count = 0
    article_count = 0
    record_count = 0
    laws: list[dict] = []

    for path in paths:
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        doc_articles, doc_records = document_stats(doc)
        law_count += 1
        article_count += doc_articles
        record_count += doc_records
        laws.append(
            {
                "law_id": doc.get("law_id", "") or doc.get("shuisho_id", ""),
                "law_name": doc.get("law_name", "") or doc.get("title", ""),
                "source_type": doc.get("source_type", "law"),
                "issue_id": doc.get("issue_id"),
                "meeting_title": doc.get("meeting_title"),
                "year_enforced": doc.get("year_enforced"),
                "article_count": doc_articles,
                "record_count": doc_records,
                "file": path.name,
            }
        )

    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "digest": corpus_digest(paths),
        "counts": {
            "laws": law_count,
            "articles": article_count,
            "records": record_count,
        },
        "laws": laws,
    }


def write_manifest(input_dir: Path, source: str = "local") -> Path:
    manifest = build_manifest(input_dir, source=source)
    path = input_dir / MANIFEST_FILENAME
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path
