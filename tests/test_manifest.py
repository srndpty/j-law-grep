import json

from indexer.manifest import build_manifest, write_manifest
from indexer.pipeline import collect_records, to_index_actions


def test_manifest_counts_and_pipeline_ignores_manifest(tmp_path):
    law = {
        "law_id": "minpou",
        "law_name": "民法",
        "articles": [
            {
                "article_no": "709",
                "paragraphs": [
                    {
                        "paragraph_no": 1,
                        "items": [
                            {"item_no": None, "text": "故意又は過失によって損害を生じさせた。"}
                        ],
                    }
                ],
            }
        ],
    }
    (tmp_path / "minpou.json").write_text(json.dumps(law, ensure_ascii=False), encoding="utf-8")

    manifest = build_manifest(tmp_path, source="test")
    assert manifest["counts"] == {"laws": 1, "articles": 1, "records": 1}
    assert manifest["laws"][0]["file"] == "minpou.json"

    write_manifest(tmp_path, source="test")
    records = collect_records(tmp_path)
    assert len(records) == 1
    assert records[0].law_name == "民法"


def test_non_numeric_item_number_is_indexed_as_label(tmp_path):
    law = {
        "law_id": "digital",
        "law_name": "デジタル庁令",
        "articles": [
            {
                "article_no": "1",
                "paragraphs": [
                    {
                        "paragraph_no": 1,
                        "items": [{"item_no": "1_2", "text": "不当に制限しないこと。"}],
                    }
                ],
            }
        ],
    }
    (tmp_path / "digital.json").write_text(json.dumps(law, ensure_ascii=False), encoding="utf-8")

    records = collect_records(tmp_path)
    actions = list(to_index_actions(records))
    assert actions[0]["_source"]["paragraph_no"] == "1"
    assert actions[0]["_source"]["item_no"] == "1_2"


def test_duplicate_positions_get_distinct_document_ids(tmp_path):
    law = {
        "law_id": "same-position",
        "law_name": "同一位置法",
        "articles": [
            {
                "article_no": "1",
                "paragraphs": [
                    {
                        "paragraph_no": 1,
                        "items": [
                            {"item_no": None, "text": "一つ目の本文。"},
                            {"item_no": None, "text": "二つ目の本文。"},
                        ],
                    }
                ],
            }
        ],
    }
    (tmp_path / "same.json").write_text(json.dumps(law, ensure_ascii=False), encoding="utf-8")

    actions = list(to_index_actions(collect_records(tmp_path)))
    assert len(actions) == 2
    assert len({action["_id"] for action in actions}) == 2


def test_manifest_counts_normalized_records(tmp_path):
    law = {
        "law_id": "blank",
        "law_name": "空白法",
        "articles": [
            {"article_no": "1", "paragraphs": [{"paragraph_no": 1, "items": [{"text": "   "}]}]},
            {"article_no": "2", "paragraphs": [{"paragraph_no": 1, "items": [{"text": "本文"}]}]},
        ],
    }
    (tmp_path / "blank.json").write_text(json.dumps(law, ensure_ascii=False), encoding="utf-8")

    manifest = build_manifest(tmp_path, source="test")
    records = collect_records(tmp_path)

    assert manifest["counts"]["records"] == len(records) == 1


def test_stable_document_ids_do_not_depend_on_previous_records(tmp_path):
    original = {
        "law_id": "stable",
        "law_name": "安定法",
        "articles": [
            {"article_no": "1", "paragraphs": [{"paragraph_no": 1, "items": [{"text": "本文"}]}]},
        ],
    }
    shifted = {
        **original,
        "articles": [
            {"article_no": "0", "paragraphs": [{"paragraph_no": 1, "items": [{"text": "前文"}]}]},
            *original["articles"],
        ],
    }
    (tmp_path / "original.json").write_text(
        json.dumps(original, ensure_ascii=False), encoding="utf-8"
    )
    original_id = list(to_index_actions(collect_records(tmp_path)))[0]["_id"]
    (tmp_path / "original.json").write_text(
        json.dumps(shifted, ensure_ascii=False), encoding="utf-8"
    )
    shifted_ids = [action["_id"] for action in to_index_actions(collect_records(tmp_path))]

    assert original_id in shifted_ids
