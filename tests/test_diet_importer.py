import json

from indexer.diet_importer import iter_issue_ids, normalize_meeting_record, write_meeting
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
