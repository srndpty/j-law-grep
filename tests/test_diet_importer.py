import json
from argparse import Namespace

import pytest

from indexer.diet_importer import iter_issue_ids, normalize_meeting_record, run_fetch, write_meeting
from indexer.manifest import build_manifest
from indexer.pipeline import collect_records, to_index_actions


def _meeting_payload() -> dict:
    return {
        "issueID": "121214601X00120240126",
        "nameOfHouse": "衆議院",
        "nameOfMeeting": "本会議",
        "session": "212",
        "issue": "1",
        "date": "2024-01-26",
        "meetingURL": "https://kokkai.ndl.go.jp/txt/121214601X00120240126",
        "pdfURL": "https://kokkai.ndl.go.jp/pdf/121214601X00120240126.pdf",
        "speechRecord": [
            {
                "speechID": "121214601X00120240126_001",
                "speechOrder": "1",
                "speaker": "議長",
                "speakerYomi": "ぎちょう",
                "speakerPosition": "議長",
                "speakerGroup": "",
                "speakerRole": "",
                "speech": "これより会議を開きます。",
                "speechURL": "https://kokkai.ndl.go.jp/txt/121214601X00120240126/1",
            },
            {
                "speechID": "blank",
                "speechOrder": "2",
                "speaker": "議長",
                "speech": "   ",
            },
        ],
    }


def test_iter_issue_ids_pages_and_deduplicates():
    calls = []

    def fetcher(path, params):
        calls.append((path, params))
        if params["startRecord"] == 1:
            return {
                "meetingRecord": [{"issueID": "a"}, {"issueID": "b"}],
                "nextRecordPosition": 3,
            }
        return {"meetingRecord": [{"issueID": "b"}, {"issueID": "c"}]}

    assert list(iter_issue_ids({"maximumRecords": 100}, fetcher=fetcher, delay_seconds=0)) == [
        "a",
        "b",
        "c",
    ]
    assert [params["startRecord"] for _, params in calls] == [1, 3]


def test_normalize_meeting_record_keeps_speech_metadata():
    meeting = normalize_meeting_record(_meeting_payload())

    assert meeting["source_type"] == "diet"
    assert meeting["meeting_title"] == "衆議院 本会議 第212回 第1号"
    assert meeting["speeches"] == [
        {
            "speech_id": "121214601X00120240126_001",
            "speech_order": "1",
            "speaker": "議長",
            "speaker_yomi": "ぎちょう",
            "speaker_group": "",
            "speaker_position": "議長",
            "speaker_role": "",
            "start_page": "",
            "speech_url": "https://kokkai.ndl.go.jp/txt/121214601X00120240126/1",
            "text": "これより会議を開きます。",
        }
    ]


def test_diet_document_flows_through_manifest_and_pipeline(tmp_path):
    meeting = normalize_meeting_record(_meeting_payload())
    write_meeting(tmp_path, meeting)

    manifest = build_manifest(tmp_path, source="diet")
    records = collect_records(tmp_path)
    action = list(to_index_actions(records))[0]

    assert manifest["counts"] == {"laws": 1, "articles": 1, "records": 1}
    assert records[0].source_type == "diet"
    assert records[0].law_name == "衆議院 本会議 第212回 第1号"
    assert action["_source"]["source_type"] == "diet"
    assert action["_source"]["issue_id"] == "121214601X00120240126"
    assert action["_source"]["house"] == "衆議院"
    assert action["_source"]["speaker"] == "議長"
    assert action["_source"]["content"] == "これより会議を開きます。"


def test_write_meeting_does_not_overwrite_by_default(tmp_path):
    meeting = normalize_meeting_record(_meeting_payload())
    path = write_meeting(tmp_path, meeting)
    path.write_text(json.dumps({"issue_id": "kept"}, ensure_ascii=False), encoding="utf-8")

    write_meeting(tmp_path, meeting)

    assert json.loads(path.read_text(encoding="utf-8")) == {"issue_id": "kept"}


def _fetch_args(tmp_path, **overrides):
    values = {
        "output": tmp_path,
        "house": "衆議院",
        "all_houses": False,
        "meeting": None,
        "from_date": None,
        "until_date": None,
        "session_from": 212,
        "session_to": 212,
        "limit_meetings": None,
        "delay_seconds": 0,
        "retries": 0,
        "retry_backoff_seconds": 0,
        "checkpoint_every": 1,
        "state_file": None,
        "errors_file": None,
        "overwrite": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_run_fetch_skips_existing_file_and_writes_checkpoint(tmp_path):
    existing = normalize_meeting_record(_meeting_payload())
    write_meeting(tmp_path, existing)
    fetched_payload = {**_meeting_payload(), "issueID": "121214601X00220240127", "issue": "2"}

    def fetcher(path, params):
        if path == "meeting_list":
            return {
                "meetingRecord": [
                    {"issueID": "121214601X00120240126"},
                    {"issueID": "121214601X00220240127"},
                ]
            }
        assert params["issueID"] == "121214601X00220240127"
        return {"meetingRecord": [fetched_payload]}

    stats = run_fetch(_fetch_args(tmp_path), fetcher=fetcher)
    state = json.loads((tmp_path / "_fetch_state.json").read_text(encoding="utf-8"))

    assert stats.discovered == 2
    assert stats.skipped == 1
    assert stats.fetched == 1
    assert sorted(state["completed_issue_ids"]) == [
        "121214601X00120240126",
        "121214601X00220240127",
    ]
    assert (tmp_path / "121214601X00220240127.json").exists()


def test_run_fetch_overwrite_refetches_completed_issue(tmp_path):
    meeting = normalize_meeting_record(_meeting_payload())
    write_meeting(tmp_path, meeting)
    (tmp_path / "_fetch_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed_issue_ids": ["121214601X00120240126"],
                "runs": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    replacement = {
        **_meeting_payload(),
        "speechRecord": [
            {
                "speechID": "121214601X00120240126_001",
                "speechOrder": "1",
                "speaker": "議長",
                "speech": "上書き後の本文です。",
            }
        ],
    }

    def fetcher(path, params):
        if path == "meeting_list":
            return {"meetingRecord": [{"issueID": "121214601X00120240126"}]}
        return {"meetingRecord": [replacement]}

    stats = run_fetch(_fetch_args(tmp_path, overwrite=True), fetcher=fetcher)
    saved = json.loads((tmp_path / "121214601X00120240126.json").read_text(encoding="utf-8"))

    assert stats.fetched == 1
    assert stats.skipped == 0
    assert saved["speeches"][0]["text"] == "上書き後の本文です。"


def test_run_fetch_records_failures_and_continues(tmp_path):
    def fetcher(path, params):
        if path == "meeting_list":
            return {
                "meetingRecord": [
                    {"issueID": "bad"},
                    {"issueID": "121214601X00120240126"},
                ]
            }
        if params["issueID"] == "bad":
            raise RuntimeError("boom")
        return {"meetingRecord": [_meeting_payload()]}

    stats = run_fetch(_fetch_args(tmp_path), fetcher=fetcher)
    errors = (tmp_path / "_fetch_errors.jsonl").read_text(encoding="utf-8").splitlines()

    assert stats.failed == 1
    assert stats.fetched == 1
    assert json.loads(errors[0])["issue_id"] == "bad"
    assert (tmp_path / "121214601X00120240126.json").exists()


def test_run_fetch_all_houses_builds_separate_scopes(tmp_path):
    seen_houses = []

    def fetcher(path, params):
        if path == "meeting_list":
            seen_houses.append(params["nameOfHouse"])
            return {"meetingRecord": []}
        raise AssertionError("meeting endpoint should not be called")

    stats = run_fetch(_fetch_args(tmp_path, all_houses=True, house=None), fetcher=fetcher)

    assert stats.discovered == 0
    assert seen_houses == ["衆議院", "参議院"]


def test_run_fetch_requires_a_scope(tmp_path):
    with pytest.raises(SystemExit, match="Specify at least one search scope"):
        run_fetch(
            _fetch_args(
                tmp_path,
                house=None,
                all_houses=False,
                session_from=None,
                session_to=None,
            ),
            fetcher=lambda path, params: {},
        )


def test_manifest_ignores_fetch_state_files(tmp_path):
    meeting = normalize_meeting_record(_meeting_payload())
    write_meeting(tmp_path, meeting)
    (tmp_path / "_fetch_state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_fetch_errors.json").write_text("{}", encoding="utf-8")

    manifest = build_manifest(tmp_path, source="diet")

    assert manifest["counts"] == {"laws": 1, "articles": 1, "records": 1}
