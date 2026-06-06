import json
import re

import pytest

from indexer import golden as golden_module
from indexer import main as indexer_main
from search import open_search_client
from search import service as search_service


class RecordingBackend:
    instances: list["RecordingBackend"] = []

    def __init__(self, index=None):
        self.index = index or "jlaw-current"
        self.created = []
        self.ensured = False
        self.bulk_calls = []
        self.prepared = []
        self.deleted = []
        self.validated = []
        self.switched = []
        self.stats_requested = []
        RecordingBackend.instances.append(self)

    def create_index(self, index):
        self.created.append(index)

    def ensure_index(self):
        self.ensured = True

    def bulk(self, actions, chunk_size, max_chunk_bytes, progress):
        self.bulk_calls.append(
            {
                "actions": list(actions),
                "chunk_size": chunk_size,
                "max_chunk_bytes": max_chunk_bytes,
                "progress": progress,
            }
        )
        return 2

    def prepare_for_search(self, forcemerge):
        self.prepared.append(forcemerge)

    def count(self):
        return 2

    def validate_schema(self, index):
        self.validated.append(index)

    def switch_alias(self, alias, target):
        self.switched.append((alias, target))

    def index_stats(self, index):
        self.stats_requested.append(index)
        return {"health": "green", "index": index}

    def delete_index(self, index):
        self.deleted.append(index)


def test_versioned_index_name_sanitizes_alias_and_adds_timestamp():
    name = indexer_main.versioned_index_name("jlaw current,*")

    assert re.fullmatch(r"jlaw-current-v\d{20}", name)


def test_run_golden_gate_writes_reports_and_raises_on_failures(monkeypatch, tmp_path, capsys):
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps([{"query": "x"}, {"query": "y"}]), encoding="utf-8")
    calls = []

    def fake_run_case(service, case, size):
        calls.append((service, case, size))
        return ([f"{case['query']} failed"] if case["query"] == "y" else []), {
            "query": case["query"],
            "ok": case["query"] == "x",
        }

    jsonl_rows = []
    markdown_rows = []
    monkeypatch.setattr(open_search_client, "OpenSearchBackend", RecordingBackend)
    monkeypatch.setattr(search_service, "SearchService", lambda backend: {"backend": backend})
    monkeypatch.setattr(golden_module, "run_case", fake_run_case)
    monkeypatch.setattr(golden_module, "write_jsonl", lambda path, rows: jsonl_rows.extend(rows))
    monkeypatch.setattr(
        golden_module, "write_markdown", lambda path, rows: markdown_rows.extend(rows)
    )

    with pytest.raises(RuntimeError, match="Golden gate failed"):
        indexer_main.run_golden_gate(
            golden_file, "jlaw-current-v1", size=5, report_path=tmp_path / "golden.jsonl"
        )

    assert [case["query"] for _, case, _ in calls] == ["x", "y"]
    assert [size for _, _, size in calls] == [5, 5]
    assert jsonl_rows == [{"query": "x", "ok": True}, {"query": "y", "ok": False}]
    assert markdown_rows == jsonl_rows
    assert "FAIL y failed" in capsys.readouterr().err


def test_run_golden_gate_prints_success(monkeypatch, tmp_path, capsys):
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps([{"query": "x"}]), encoding="utf-8")
    monkeypatch.setattr(open_search_client, "OpenSearchBackend", RecordingBackend)
    monkeypatch.setattr(search_service, "SearchService", lambda backend: {"backend": backend})
    monkeypatch.setattr(
        golden_module,
        "run_case",
        lambda service, case, size: ([], {"query": case["query"], "ok": True}),
    )

    indexer_main.run_golden_gate(golden_file, "jlaw-current-v1")

    assert "Golden gate passed for jlaw-current-v1: 1 cases" in capsys.readouterr().out


def test_main_indexes_non_versioned_corpus_and_writes_stats(monkeypatch, tmp_path, capsys):
    RecordingBackend.instances = []
    report_dir = tmp_path / "report"
    monkeypatch.setattr(indexer_main, "OpenSearchBackend", RecordingBackend)
    monkeypatch.setattr(
        indexer_main,
        "build_manifest",
        lambda path, source: {"counts": {"records": 2}, "path": str(path), "source": source},
    )
    monkeypatch.setattr(indexer_main, "iter_records", lambda path, show_progress: ["r1", "r2"])
    monkeypatch.setattr(
        indexer_main, "to_index_actions", lambda records: ({"id": r} for r in records)
    )
    monkeypatch.setattr(
        indexer_main.sys,
        "argv",
        [
            "indexer",
            "--input",
            str(tmp_path),
            "--index",
            "custom-index",
            "--chunk-size",
            "7",
            "--max-bulk-mb",
            "2",
            "--progress",
            "--report-dir",
            str(report_dir),
        ],
    )

    indexer_main.main()

    backend = RecordingBackend.instances[0]
    assert backend.index == "custom-index"
    assert backend.ensured is True
    assert backend.bulk_calls == [
        {
            "actions": [{"id": "r1"}, {"id": "r2"}],
            "chunk_size": 7,
            "max_chunk_bytes": 2 * 1024 * 1024,
            "progress": True,
        }
    ]
    assert backend.prepared == [False]
    assert (
        json.loads((report_dir / "index_stats.json").read_text(encoding="utf-8"))["health"]
        == "green"
    )
    assert "Indexed 2 records into custom-index" in capsys.readouterr().out


def test_main_versioned_requires_alias(monkeypatch, tmp_path):
    monkeypatch.setattr(
        indexer_main.sys, "argv", ["indexer", "--input", str(tmp_path), "--versioned"]
    )
    monkeypatch.setattr(
        indexer_main, "build_manifest", lambda path, source: {"counts": {"records": 0}}
    )
    monkeypatch.delenv("OPENSEARCH_INDEX", raising=False)

    with pytest.raises(SystemExit, match="--versioned requires --alias"):
        indexer_main.main()


def test_main_versioned_success_switches_alias_after_golden(monkeypatch, tmp_path, capsys):
    RecordingBackend.instances = []
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")
    golden_file = tmp_path / "golden.json"
    golden_file.write_text("[]", encoding="utf-8")
    report_dir = tmp_path / "report"
    golden_calls = []

    monkeypatch.setattr(indexer_main, "OpenSearchBackend", RecordingBackend)
    monkeypatch.setattr(indexer_main, "versioned_index_name", lambda alias: f"{alias}-vfixed")
    monkeypatch.setattr(indexer_main, "write_manifest", lambda path, source: manifest_file)
    monkeypatch.setattr(
        indexer_main.shutil,
        "copyfile",
        lambda src, dst: dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8"),
    )
    monkeypatch.setattr(
        indexer_main, "build_manifest", lambda path, source: {"counts": {"records": 2}}
    )
    monkeypatch.setattr(indexer_main, "iter_records", lambda path, show_progress: ["r1", "r2"])
    monkeypatch.setattr(
        indexer_main, "to_index_actions", lambda records: ({"id": r} for r in records)
    )
    monkeypatch.setattr(
        indexer_main,
        "run_golden_gate",
        lambda golden, index, report_path: golden_calls.append((golden, index, report_path)),
    )
    monkeypatch.setattr(
        indexer_main.sys,
        "argv",
        [
            "indexer",
            "--input",
            str(tmp_path),
            "--alias",
            "jlaw-current",
            "--versioned",
            "--golden",
            str(golden_file),
            "--write-manifest",
            "--forcemerge",
            "--report-dir",
            str(report_dir),
        ],
    )

    indexer_main.main()

    backend = RecordingBackend.instances[0]
    assert backend.created == ["jlaw-current-vfixed"]
    assert backend.validated == ["jlaw-current-vfixed"]
    assert backend.prepared == [True]
    assert backend.switched == [("jlaw-current", "jlaw-current-vfixed")]
    assert backend.deleted == []
    assert golden_calls == [
        (golden_file, "jlaw-current-vfixed", report_dir / "golden_report.jsonl")
    ]
    assert (report_dir / "manifest.json").exists()
    assert "Switched alias jlaw-current -> jlaw-current-vfixed" in capsys.readouterr().out


def test_main_versioned_deletes_failed_index(monkeypatch, tmp_path, capsys):
    RecordingBackend.instances = []
    monkeypatch.setattr(indexer_main, "OpenSearchBackend", RecordingBackend)
    monkeypatch.setattr(indexer_main, "versioned_index_name", lambda alias: f"{alias}-vfailed")
    monkeypatch.setattr(
        indexer_main, "build_manifest", lambda path, source: {"counts": {"records": 3}}
    )
    monkeypatch.setattr(indexer_main, "iter_records", lambda path, show_progress: ["r1", "r2"])
    monkeypatch.setattr(
        indexer_main, "to_index_actions", lambda records: ({"id": r} for r in records)
    )
    monkeypatch.setattr(
        indexer_main.sys,
        "argv",
        ["indexer", "--input", str(tmp_path), "--alias", "jlaw-current", "--versioned"],
    )

    with pytest.raises(RuntimeError, match="Indexed record count mismatch"):
        indexer_main.main()

    assert RecordingBackend.instances[0].deleted == ["jlaw-current-vfailed"]
    assert "Deleted failed versioned index: jlaw-current-vfailed" in capsys.readouterr().err
