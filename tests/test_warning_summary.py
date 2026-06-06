import json
import sys

import pytest

from indexer import warning_summary


def test_load_warnings_reads_jsonl_and_skips_blank_lines(tmp_path):
    path = tmp_path / "warnings.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"code": "missing_article", "law_id": "law-1"}),
                "",
                json.dumps({"code": "missing_article", "law_id": "law-2"}),
                json.dumps({"law_id": "law-1"}),
            ]
        ),
        encoding="utf-8",
    )

    warnings = warning_summary.load_warnings(path)

    assert warnings == [
        {"code": "missing_article", "law_id": "law-1"},
        {"code": "missing_article", "law_id": "law-2"},
        {"law_id": "law-1"},
    ]


def test_load_warnings_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Warning file not found"):
        warning_summary.load_warnings(tmp_path / "missing.jsonl")


def test_summarize_counts_codes_and_top_laws():
    summary = warning_summary.summarize(
        [
            {"code": "b", "law_id": "law-1"},
            {"code": "a", "law_id": "law-1"},
            {"code": "b", "law_id": "law-2"},
            {},
        ]
    )

    assert summary == {
        "total": 4,
        "by_code": {"a": 1, "b": 2, "unknown": 1},
        "top_affected_laws": [("law-1", 2), ("law-2", 1)],
    }


def test_write_and_print_summary(tmp_path, capsys):
    summary = {
        "total": 2,
        "by_code": {"missing": 2},
        "top_affected_laws": [("law-1", 2)],
    }
    out = tmp_path / "summary" / "warnings.json"

    warning_summary.write_summary(out, summary)
    warning_summary.print_summary(summary)

    assert json.loads(out.read_text(encoding="utf-8")) == {
        "total": 2,
        "by_code": {"missing": 2},
        "top_affected_laws": [["law-1", 2]],
    }
    printed = capsys.readouterr().out
    assert "total: 2" in printed
    assert "- law-1: 2" in printed


def test_main_writes_json_summary(monkeypatch, tmp_path, capsys):
    warnings = tmp_path / "warnings.jsonl"
    out = tmp_path / "summary.json"
    warnings.write_text(json.dumps({"code": "x", "law_id": "law-1"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["warning_summary", str(warnings), "--json-out", str(out)])

    warning_summary.main()

    assert json.loads(out.read_text(encoding="utf-8"))["total"] == 1
    assert "x: 1" in capsys.readouterr().out
