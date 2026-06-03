from pathlib import Path

from indexer.schema import (
    WARN_EMPTY_LAW,
    WARN_EMPTY_LAW_ID,
    WARN_MISSING_ARTICLE_NO,
    WARN_SHORT_CONTENT,
    WARN_UNSUPPORTED_ITEM_NO,
    is_recognized_item_no,
    validate_law_document,
    write_warnings_jsonl,
)


def _doc(**overrides) -> dict:
    base = {
        "law_id": "minpou",
        "law_name": "民法",
        "law_aliases": [],
        "articles": [
            {
                "article_no": "709",
                "heading": "",
                "paragraphs": [{"paragraph_no": 1, "items": [{"item_no": None, "text": "本文。"}]}],
            }
        ],
    }
    base.update(overrides)
    return base


def _codes(doc: dict) -> set[str]:
    return {w.code for w in validate_law_document(doc)}


def test_clean_document_has_no_warnings():
    assert validate_law_document(_doc()) == []


def test_empty_law_id_is_flagged():
    assert WARN_EMPTY_LAW_ID in _codes(_doc(law_id=""))


def test_no_articles_is_empty_law():
    assert WARN_EMPTY_LAW in _codes(_doc(articles=[]))


def test_no_usable_text_is_empty_law():
    doc = _doc(
        articles=[{"article_no": "1", "paragraphs": [{"items": [{"item_no": None, "text": ""}]}]}]
    )
    assert WARN_EMPTY_LAW in _codes(doc)


def test_missing_article_no_is_flagged():
    doc = _doc(
        articles=[
            {"article_no": "", "paragraphs": [{"items": [{"item_no": None, "text": "本文。"}]}]}
        ]
    )
    assert WARN_MISSING_ARTICLE_NO in _codes(doc)


def test_short_content_is_flagged():
    doc = _doc(
        articles=[{"article_no": "1", "paragraphs": [{"items": [{"item_no": None, "text": "あ"}]}]}]
    )
    assert WARN_SHORT_CONTENT in _codes(doc)


def test_unsupported_item_no_is_flagged():
    doc = _doc(
        articles=[
            {
                "article_no": "1",
                "paragraphs": [{"items": [{"item_no": "(a)", "text": "本文の内容。"}]}],
            }
        ]
    )
    assert WARN_UNSUPPORTED_ITEM_NO in _codes(doc)


def test_is_recognized_item_no_accepts_known_forms():
    assert is_recognized_item_no(None)
    assert is_recognized_item_no(1)
    assert is_recognized_item_no("一")
    assert is_recognized_item_no("第一号")
    assert is_recognized_item_no("イ")
    assert not is_recognized_item_no("(a)")


def test_write_warnings_jsonl_roundtrip(tmp_path: Path):
    doc = _doc(law_id="", articles=[])
    warnings = validate_law_document(doc)
    out = tmp_path / "w.jsonl"
    written = write_warnings_jsonl(out, warnings)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert written == len(warnings)
    assert len(lines) == written
