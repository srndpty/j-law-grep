from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

from search.citation import Citation, citation_key

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional dependency
    tqdm = None
from indexer.manifest import iter_corpus_json_paths
from indexer.utils import normalize_text

CONTENT_LONG_MAX_BYTES = 8192


def issue_label(issue: str) -> str:
    issue = normalize_text(issue)
    if not issue:
        return ""
    if issue.startswith("第") or issue.endswith("号"):
        return issue
    return f"第{issue}号"


@dataclass
class IndexRecord:
    source_type: str
    law_id: str
    law_name: str
    law_aliases: list[str]
    article_no: str
    paragraph_no: str | None
    item_no: str | None
    caption: str
    heading: str
    content: str
    content_plain: str
    citation: Citation
    year_enforced: str | None
    path: str
    url: str
    blocks: list[dict]
    issue_id: str | None = None
    house: str | None = None
    meeting_name: str | None = None
    session: str | None = None
    issue: str | None = None
    date: str | None = None
    speaker: str | None = None
    speaker_yomi: str | None = None
    speaker_group: str | None = None
    speaker_position: str | None = None
    speaker_role: str | None = None
    speech_id: str | None = None
    speech_order: str | None = None
    pdf_url: str | None = None


def load_documents(input_dir: Path) -> Iterable[dict]:
    for path in iter_corpus_json_paths(input_dir):
        with path.open("r", encoding="utf-8") as fh:
            yield json.load(fh)


def position_label(value: object) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    return label or None


def iter_documents(input_dir: Path, show_progress: bool = False) -> Iterable[dict]:
    if show_progress and tqdm:
        paths = list(iter_corpus_json_paths(input_dir))
        iterator = tqdm(paths, desc="Loading corpus", unit="file")
        for path in iterator:
            with path.open("r", encoding="utf-8") as fh:
                yield json.load(fh)
        return
    yield from load_documents(input_dir)


def iter_records(input_dir: Path, show_progress: bool = False) -> Iterator[IndexRecord]:
    for doc in iter_documents(input_dir, show_progress=show_progress):
        yield from records_from_document(doc)


def collect_records(input_dir: Path, show_progress: bool = False) -> list[IndexRecord]:
    return list(iter_records(input_dir, show_progress=show_progress))


def truncate_utf8(value: str, max_bytes: int = CONTENT_LONG_MAX_BYTES) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def records_from_document(doc: dict) -> Iterator[IndexRecord]:
    if doc.get("source_type") == "diet":
        yield from diet_records_from_document(doc)
        return

    law_id = doc["law_id"]
    law_name = doc["law_name"]
    law_aliases = doc.get("law_aliases", [])
    year_enforced = doc.get("year_enforced")
    for article in doc.get("articles", []):
        article_no = str(article["article_no"])
        caption = normalize_text(article.get("caption", ""))
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
                paragraph_label = position_label(paragraph_no)
                item_label = position_label(item_no)
                citation = Citation(
                    law_name=law_name,
                    article_no=article_no,
                    paragraph_no=int(paragraph_label)
                    if paragraph_label and paragraph_label.isdigit()
                    else None,
                    item_no=int(item_label) if item_label and item_label.isdigit() else None,
                )
                blocks = [
                    {
                        "kind": "text",
                        "html": text,
                    }
                ]
                path = f"{law_name}/{article_no}"
                url = f"/l/{law_id}/a/{article_no}"
                if paragraph_label:
                    url += f"/{paragraph_label}"
                if item_label:
                    url += f"/{item_label}"
                yield IndexRecord(
                    source_type="law",
                    law_id=law_id,
                    law_name=law_name,
                    law_aliases=law_aliases,
                    article_no=article_no,
                    paragraph_no=paragraph_label,
                    item_no=item_label,
                    caption=caption,
                    heading=heading,
                    content=text,
                    content_plain=text,
                    citation=citation,
                    year_enforced=year_enforced,
                    path=path,
                    url=url,
                    blocks=blocks,
                )


def diet_records_from_document(doc: dict) -> Iterator[IndexRecord]:
    issue_id = normalize_text(str(doc.get("issue_id") or ""))
    house = normalize_text(str(doc.get("house") or ""))
    meeting_name = normalize_text(str(doc.get("meeting_name") or ""))
    session = normalize_text(str(doc.get("session") or ""))
    issue = normalize_text(str(doc.get("issue") or ""))
    date = normalize_text(str(doc.get("date") or ""))
    rebuilt_title = " ".join(
        part
        for part in (house, meeting_name, f"第{session}回" if session else "", issue_label(issue))
        if part
    )
    meeting_title = rebuilt_title or normalize_text(str(doc.get("meeting_title") or "")) or issue_id
    meeting_url = normalize_text(str(doc.get("meeting_url") or ""))
    pdf_url = normalize_text(str(doc.get("pdf_url") or ""))

    for index, speech in enumerate(doc.get("speeches", []) or [], start=1):
        text = normalize_text(str(speech.get("text") or ""))
        if not text:
            continue
        speech_order = normalize_text(str(speech.get("speech_order") or "")) or str(index)
        speech_id = normalize_text(str(speech.get("speech_id") or ""))
        speaker = normalize_text(str(speech.get("speaker") or ""))
        speaker_position = normalize_text(str(speech.get("speaker_position") or ""))
        speech_url = normalize_text(str(speech.get("speech_url") or "")) or meeting_url
        path = "/".join(
            part
            for part in (
                "国会会議録",
                house,
                meeting_name,
                f"第{session}回" if session else "",
                issue_label(issue),
                f"発言{speech_order}",
            )
            if part
        )
        heading = " ".join(part for part in (speaker, speaker_position) if part)
        # Diet speeches are plain text from the Kokkai API (already normalized),
        # so store them under `text` rather than `html` to avoid implying the
        # value is a safe HTML fragment.
        blocks = [
            {
                "kind": "speech",
                "speaker": speaker,
                "text": text,
            }
        ]
        yield IndexRecord(
            source_type="diet",
            law_id=issue_id,
            law_name=meeting_title,
            law_aliases=[],
            article_no=speech_order,
            paragraph_no=None,
            item_no=None,
            caption=meeting_name,
            heading=normalize_text(heading),
            content=text,
            content_plain=text,
            citation=Citation(
                law_name=meeting_title,
                article_no=speech_order,
                paragraph_no=None,
                item_no=None,
            ),
            year_enforced=date[:4] if len(date) >= 4 else None,
            path=path,
            url=speech_url,
            blocks=blocks,
            issue_id=issue_id,
            house=house,
            meeting_name=meeting_name,
            session=session,
            issue=issue,
            date=date or None,
            speaker=speaker,
            speaker_yomi=normalize_text(str(speech.get("speaker_yomi") or "")),
            speaker_group=normalize_text(str(speech.get("speaker_group") or "")),
            speaker_position=speaker_position,
            speaker_role=normalize_text(str(speech.get("speaker_role") or "")),
            speech_id=speech_id,
            speech_order=speech_order,
            pdf_url=pdf_url,
        )


def to_index_actions(records: Iterable[IndexRecord]) -> Iterator[dict]:
    seen: dict[str, int] = {}
    for record in records:
        citation = citation_key(record.citation)
        doc = {
            "source_type": record.source_type,
            "law_id": record.law_id,
            "law_name": record.law_name,
            "law_aliases": record.law_aliases,
            "article_no": record.article_no,
            "paragraph_no": record.paragraph_no,
            "item_no": record.item_no,
            "citation_key": citation,
            "caption": record.caption,
            "heading": record.heading,
            "content": record.content,
            "content_long": truncate_utf8(record.content),
            "content_plain": record.content_plain,
            "year_enforced": record.year_enforced,
            "path": record.path,
            "url": record.url,
            "line": 0,
            "blocks": record.blocks,
        }
        if record.source_type == "diet":
            doc |= {
                "issue_id": record.issue_id,
                "house": record.house,
                "meeting_name": record.meeting_name,
                "session": record.session,
                "issue": record.issue,
                "date": record.date,
                "speaker": record.speaker,
                "speaker_yomi": record.speaker_yomi,
                "speaker_group": record.speaker_group,
                "speaker_position": record.speaker_position,
                "speaker_role": record.speaker_role,
                "speech_id": record.speech_id,
                "speech_order": record.speech_order,
                "pdf_url": record.pdf_url,
            }
        base_doc_id = stable_doc_id(record)
        seen[base_doc_id] = seen.get(base_doc_id, 0) + 1
        doc_id = base_doc_id if seen[base_doc_id] == 1 else f"{base_doc_id}-{seen[base_doc_id]}"
        yield {"_id": doc_id, "_source": doc}


def stable_doc_id(record: IndexRecord) -> str:
    content_digest = sha1(record.content.encode("utf-8")).hexdigest()[:12]
    key = "\0".join(
        [
            record.source_type,
            record.law_id,
            record.article_no,
            record.paragraph_no or "",
            record.item_no or "",
            content_digest,
        ]
    )
    digest = sha1(key.encode("utf-8")).hexdigest()[:20]
    return f"{record.law_id}-{record.article_no}-{record.paragraph_no or 0}-{record.item_no or 0}-{digest}"
