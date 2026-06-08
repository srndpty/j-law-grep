from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from indexer.utils import normalize_text

API_BASE_URL = "https://kokkai.ndl.go.jp/api"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "indexer" / "diet_data"
USER_AGENT = "j-law-grep/0.1 (+https://github.com/)"


def issue_label(issue: str) -> str:
    issue = normalize_text(issue)
    if not issue:
        return ""
    if issue.startswith("第") or issue.endswith("号"):
        return issue
    return f"第{issue}号"


def fetch_json(path: str, params: dict[str, str | int], timeout: int = 60) -> dict[str, Any]:
    query = urlencode({**params, "recordPacking": "json"})
    request = Request(
        f"{API_BASE_URL}/{path}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - official public API
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"Kokkai API HTTP error: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Kokkai API request failed: {exc.reason}") from exc
    return json.loads(payload)


def build_search_params(args: argparse.Namespace) -> dict[str, str | int]:
    params: dict[str, str | int] = {"maximumRecords": 100}
    if args.house:
        params["nameOfHouse"] = args.house
    if args.from_date:
        params["from"] = args.from_date
    if args.until_date:
        params["until"] = args.until_date
    if args.session_from is not None:
        params["sessionFrom"] = args.session_from
    if args.session_to is not None:
        params["sessionTo"] = args.session_to
    if args.meeting:
        params["nameOfMeeting"] = args.meeting
    return params


def iter_issue_ids(
    params: dict[str, str | int],
    fetcher: Callable[[str, dict[str, str | int]], dict[str, Any]] = fetch_json,
    delay_seconds: float = 3.0,
) -> Iterator[str]:
    start_record = 1
    seen: set[str] = set()
    while True:
        payload = fetcher("meeting_list", {**params, "startRecord": start_record})
        for meeting in payload.get("meetingRecord", []) or []:
            issue_id = normalize_text(str(meeting.get("issueID") or ""))
            if issue_id and issue_id not in seen:
                seen.add(issue_id)
                yield issue_id

        next_record = payload.get("nextRecordPosition")
        if not next_record:
            break
        start_record = int(next_record)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


def fetch_meeting(
    issue_id: str,
    fetcher: Callable[[str, dict[str, str | int]], dict[str, Any]] = fetch_json,
) -> dict[str, Any] | None:
    payload = fetcher("meeting", {"issueID": issue_id, "maximumRecords": 1})
    meetings = payload.get("meetingRecord", []) or []
    if not meetings:
        return None
    return normalize_meeting_record(meetings[0])


def normalize_meeting_record(meeting: dict[str, Any]) -> dict[str, Any]:
    issue_id = normalize_text(str(meeting.get("issueID") or ""))
    house = normalize_text(str(meeting.get("nameOfHouse") or ""))
    meeting_name = normalize_text(str(meeting.get("nameOfMeeting") or ""))
    session = normalize_text(str(meeting.get("session") or ""))
    issue = normalize_text(str(meeting.get("issue") or ""))
    date = normalize_text(str(meeting.get("date") or ""))
    title_parts = [
        part for part in (house, meeting_name, f"第{session}回", issue_label(issue)) if part
    ]
    meeting_title = " ".join(title_parts)

    speeches: list[dict[str, Any]] = []
    for speech in meeting.get("speechRecord", []) or []:
        speech_text = normalize_text(str(speech.get("speech") or ""))
        if not speech_text:
            continue
        speeches.append(
            {
                "speech_id": normalize_text(str(speech.get("speechID") or "")),
                "speech_order": normalize_text(str(speech.get("speechOrder") or "")),
                "speaker": normalize_text(str(speech.get("speaker") or "")),
                "speaker_yomi": normalize_text(str(speech.get("speakerYomi") or "")),
                "speaker_group": normalize_text(str(speech.get("speakerGroup") or "")),
                "speaker_position": normalize_text(str(speech.get("speakerPosition") or "")),
                "speaker_role": normalize_text(str(speech.get("speakerRole") or "")),
                "start_page": normalize_text(str(speech.get("startPage") or "")),
                "speech_url": normalize_text(str(speech.get("speechURL") or "")),
                "text": speech_text,
            }
        )

    return {
        "source_type": "diet",
        "issue_id": issue_id,
        "meeting_title": meeting_title or issue_id,
        "house": house,
        "meeting_name": meeting_name,
        "session": session,
        "issue": issue,
        "date": date,
        "closing": normalize_text(str(meeting.get("closing") or "")),
        "image_kind": normalize_text(str(meeting.get("imageKind") or "")),
        "search_object": normalize_text(str(meeting.get("searchObject") or "")),
        "meeting_url": normalize_text(str(meeting.get("meetingURL") or "")),
        "pdf_url": normalize_text(str(meeting.get("pdfURL") or "")),
        "speeches": speeches,
    }


def write_meeting(output_dir: Path, meeting: dict[str, Any], overwrite: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    issue_id = meeting["issue_id"]
    path = output_dir / f"{issue_id}.json"
    if path.exists() and not overwrite:
        return path
    with path.open("w", encoding="utf-8") as fh:
        json.dump(meeting, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch National Diet meeting records")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--house", choices=["衆議院", "参議院", "両院", "両院協議会"])
    parser.add_argument("--meeting", help="Meeting name substring, e.g. 予算委員会")
    parser.add_argument("--from-date", dest="from_date", help="YYYY-MM-DD")
    parser.add_argument("--until-date", dest="until_date", help="YYYY-MM-DD")
    parser.add_argument("--session-from", type=int)
    parser.add_argument("--session-to", type=int)
    parser.add_argument("--limit-meetings", type=int)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    params = build_search_params(args)
    if not any(
        key in params
        for key in ("nameOfHouse", "from", "until", "sessionFrom", "sessionTo", "nameOfMeeting")
    ):
        raise SystemExit("Specify at least one search scope, such as --session-from/--session-to.")

    fetched = 0
    for issue_id in iter_issue_ids(params, delay_seconds=args.delay_seconds):
        if args.limit_meetings is not None and fetched >= args.limit_meetings:
            break
        meeting = fetch_meeting(issue_id)
        if meeting is None:
            continue
        path = write_meeting(args.output, meeting, overwrite=args.overwrite)
        fetched += 1
        print(f"Wrote {path}")
        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)
    print(f"Fetched {fetched} meeting(s) into {args.output}")


if __name__ == "__main__":
    main()
