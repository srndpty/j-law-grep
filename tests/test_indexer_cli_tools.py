import json

import pytest

from indexer import cleanup_indices, golden, index_report, rollback_index, validate_index


class DummyBackend:
    instances: list["DummyBackend"] = []

    def __init__(self, index="jlaw-current"):
        self.index = index
        self.deleted = []
        self.validated = []
        self.switched = []
        DummyBackend.instances.append(self)

    def indices_for_alias(self, alias):
        assert alias == "jlaw-current"
        return ["jlaw-current-v3"]

    def all_indices(self, pattern):
        assert pattern == "jlaw-current-v*"
        return ["jlaw-current-v1", "jlaw-current-v2", "jlaw-current-v3", "jlaw-current-v4"]

    def delete_index(self, index):
        self.deleted.append(index)

    def concrete_indices(self, alias):
        return [f"{alias}-v3"]

    def schema_versions(self, alias):
        return {f"{alias}-v3": 4}

    def count(self, index=None):
        return 3

    def index_stats(self, alias):
        return {"health": "green", "docs": 3}

    def validate_schema(self, index):
        self.validated.append(index)

    def switch_alias(self, alias, target):
        self.switched.append((alias, target))


def test_cleanup_dry_run_keeps_latest_non_live_generations(monkeypatch, capsys):
    DummyBackend.instances = []
    monkeypatch.setattr(cleanup_indices, "OpenSearchBackend", DummyBackend)

    deleted = cleanup_indices.cleanup("jlaw-current", keep=1, force=False)

    assert deleted == ["jlaw-current-v1", "jlaw-current-v2"]
    assert DummyBackend.instances[0].deleted == []
    assert "DRY-RUN delete: jlaw-current-v1" in capsys.readouterr().out


def test_cleanup_force_deletes_candidates(monkeypatch):
    DummyBackend.instances = []
    monkeypatch.setattr(cleanup_indices, "OpenSearchBackend", DummyBackend)

    deleted = cleanup_indices.cleanup("jlaw-current", keep=0, force=True)

    assert deleted == ["jlaw-current-v1", "jlaw-current-v2", "jlaw-current-v4"]
    assert DummyBackend.instances[0].deleted == deleted


def test_cleanup_rejects_negative_keep():
    with pytest.raises(ValueError, match="--keep"):
        cleanup_indices.cleanup("jlaw-current", keep=-1, force=False)


def test_index_report_builds_summary_from_backend(monkeypatch):
    monkeypatch.setattr(index_report, "OpenSearchBackend", DummyBackend)

    report = index_report.build_report("jlaw-current")

    assert report == {
        "alias": "jlaw-current",
        "concrete_indices": ["jlaw-current-v3"],
        "schema_versions": {"jlaw-current-v3": 4},
        "doc_count": 3,
        "health": "green",
        "old_generations": ["jlaw-current-v1", "jlaw-current-v2", "jlaw-current-v4"],
    }


def test_index_report_main_writes_json(monkeypatch, tmp_path, capsys):
    out = tmp_path / "reports" / "index.json"
    monkeypatch.setattr(index_report, "OpenSearchBackend", DummyBackend)
    monkeypatch.setattr(index_report.sys, "argv", ["index_report", "--json-out", str(out)])

    index_report.main()

    assert json.loads(out.read_text(encoding="utf-8"))["doc_count"] == 3
    assert '"alias": "jlaw-current"' in capsys.readouterr().out


def test_validate_index_accepts_matching_manifest(monkeypatch, tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"counts": {"records": 3}}), encoding="utf-8")
    monkeypatch.setattr(validate_index, "OpenSearchBackend", DummyBackend)
    monkeypatch.setattr(
        validate_index.sys,
        "argv",
        ["validate_index", "--manifest", str(manifest), "--index", "jlaw-current"],
    )

    validate_index.main()

    out = capsys.readouterr().out
    assert "expected_records: 3" in out
    assert "actual_records: 3" in out


def test_validate_index_exits_when_count_mismatches(monkeypatch, tmp_path):
    class CountMismatchBackend(DummyBackend):
        def count(self, index=None):
            return 2

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"counts": {"records": 3}}), encoding="utf-8")
    monkeypatch.setattr(validate_index, "OpenSearchBackend", CountMismatchBackend)
    monkeypatch.setattr(validate_index.sys, "argv", ["validate_index", "--manifest", str(manifest)])

    with pytest.raises(SystemExit) as exc:
        validate_index.main()

    assert exc.value.code == 1


def test_rollback_validates_schema_before_switching(monkeypatch, capsys):
    DummyBackend.instances = []
    monkeypatch.setattr(rollback_index, "OpenSearchBackend", DummyBackend)
    monkeypatch.setattr(
        rollback_index.sys,
        "argv",
        ["rollback_index", "--alias", "jlaw-current", "--to", "jlaw-current-v2"],
    )

    rollback_index.main()

    backend = DummyBackend.instances[0]
    assert backend.validated == ["jlaw-current-v2"]
    assert backend.switched == [("jlaw-current", "jlaw-current-v2")]
    assert "Switched alias jlaw-current -> jlaw-current-v2" in capsys.readouterr().out


class FakeSearchService:
    def __init__(self, hits, total=1, took_ms=7):
        self.hits = hits
        self.total = total
        self.took_ms = took_ms
        self.params = []

    def search(self, params):
        self.params.append(params)
        return {
            "hits": self.hits,
            "total": self.total,
            "took_ms": self.took_ms,
            "index": {"name": "laws"},
        }


def test_golden_run_case_reports_success_for_expected_hit():
    service = FakeSearchService(
        [{"law_id": "minpo", "law_name": "民法", "article_no": "709", "paragraph_no": "1"}]
    )
    case = {
        "query": "損害",
        "mode": "keyword",
        "filters": {"law_name": "民法"},
        "expected_top": [{"law_id": "minpo"}],
        "expected_contains": ["709"],
        "not_expected_contains": ["刑法"],
        "min_total": 1,
        "max_wall_ms": 10_000,
    }

    failures, report = golden.run_case(service, case, size=20)

    assert failures == []
    assert report["ok"] is True
    assert report["top"]["article_no"] == "709"
    assert service.params[0].q == "損害"
    assert service.params[0].size == 20


def test_golden_run_case_collects_all_failure_types():
    service = FakeSearchService([{"law_id": "keihou", "law_name": "刑法"}], total=0)
    case = {
        "query": "損害",
        "expected_top": [{"law_id": "minpo"}],
        "expected_top_any": [{"law_id": "shouhou"}],
        "expected_contains": [{"article_no": "709"}],
        "not_expected_contains": [{"law_id": "keihou"}],
        "min_total": 1,
        "max_wall_ms": -1,
    }

    failures, report = golden.run_case(service, case, size=10)

    assert len(failures) == 6
    assert report["ok"] is False
    assert any("top hit did not match" in failure for failure in failures)
    assert any("unexpected hit" in failure for failure in failures)


def test_golden_writes_jsonl_and_markdown(tmp_path):
    rows = [
        {
            "query": "a|b",
            "mode": "literal",
            "ok": True,
            "total": 1,
            "took_ms": 2,
            "wall_ms": 3,
            "top": {"law_name": "民法", "article_no": "709"},
        },
        {
            "query": "c",
            "mode": "keyword",
            "ok": False,
            "total": 0,
            "took_ms": 1,
            "wall_ms": 4,
            "top": None,
        },
    ]
    jsonl = tmp_path / "nested" / "report.jsonl"
    markdown = tmp_path / "nested" / "report.md"

    golden.write_jsonl(jsonl, rows)
    golden.write_markdown(markdown, rows)

    assert [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()] == rows
    md = markdown.read_text(encoding="utf-8")
    assert "Passed: 1 / 2" in md
    assert "a\\|b" in md


def test_golden_main_exits_nonzero_on_failures(monkeypatch, tmp_path, capsys):
    case_file = tmp_path / "cases.json"
    case_file.write_text(
        json.dumps([{"query": "x", "expected_contains": ["missing"]}]), encoding="utf-8"
    )
    monkeypatch.setattr(golden, "SearchService", lambda: FakeSearchService([]))
    monkeypatch.setattr(golden.sys, "argv", ["golden", "--file", str(case_file)])

    with pytest.raises(SystemExit) as exc:
        golden.main()

    assert exc.value.code == 1
    assert "FAIL" in capsys.readouterr().err


def test_golden_main_prints_success(monkeypatch, tmp_path, capsys):
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps([{"query": "x"}]), encoding="utf-8")
    monkeypatch.setattr(golden, "SearchService", lambda: FakeSearchService([]))
    monkeypatch.setattr(golden.sys, "argv", ["golden", "--file", str(case_file)])

    golden.main()

    assert "Golden queries passed: 1" in capsys.readouterr().out
