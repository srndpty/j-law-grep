from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from indexer.utils import normalize_text

API_BASE_URL = "https://kokkai.ndl.go.jp/api"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "indexer" / "diet_data"
USER_AGENT = "j-law-grep/0.1 (+https://github.com/)"
DEFAULT_HOUSES = ("衆議院", "参議院")
FETCH_STATE_FILENAME = "_fetch_state.json"
FETCH_ERRORS_FILENAME = "_fetch_errors.jsonl"


@dataclass
class FetchStats:
    discovered: int = 0
    fetched: int = 0
    skipped: int = 0
    failed: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def issue_label(issue: str) -> str:
    issue = normalize_text(issue)
    if not issue:
        return ""
    if issue.startswith("第") or issue.endswith("号"):
        return issue
    return f"第{issue}号"


def fetch_json_once(path: str, params: dict[str, str | int], timeout: int = 60) -> dict[str, Any]:
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


def fetch_json(
    path: str,
    params: dict[str, str | int],
    timeout: int = 60,
    retries: int = 3,
    retry_backoff_seconds: float = 10.0,
) -> dict[str, Any]:
    last_error: RuntimeError | None = None
    for attempt in range(retries + 1):
        try:
            return fetch_json_once(path, params, timeout=timeout)
        except RuntimeError as exc:
            last_error = exc
            if attempt >= retries:
                break
            if retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds * (attempt + 1))
    assert last_error is not None
    raise last_error


def build_search_params(args: argparse.Namespace) -> dict[str, str | int]:
    params: dict[str, str | int] = {"maximumRecords": 100}
    if args.house and not args.all_houses:
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


def build_search_scopes(args: argparse.Namespace) -> list[dict[str, str | int]]:
    base_params = build_search_params(args)
    houses = list(DEFAULT_HOUSES) if args.all_houses else [args.house] if args.house else [None]
    scopes: list[dict[str, str | int]] = []
    for house in houses:
        params = dict(base_params)
        if house:
            params["nameOfHouse"] = house
        scopes.append(params)
    return scopes


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


def issue_path(output_dir: Path, issue_id: str) -> Path:
    return output_dir / f"{issue_id}.json"


def load_fetch_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "completed_issue_ids": [],
            "runs": [],
        }
    with path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)
    state.setdefault("completed_issue_ids", [])
    state.setdefault("runs", [])
    return state


def save_fetch_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def append_fetch_error(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")


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
    path = issue_path(output_dir, issue_id)
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
    parser.add_argument(
        "--all-houses",
        action="store_true",
        help="Fetch both House of Representatives and House of Councillors scopes.",
    )
    parser.add_argument("--meeting", help="Meeting name substring, e.g. 予算委員会")
    parser.add_argument("--from-date", dest="from_date", help="YYYY-MM-DD")
    parser.add_argument("--until-date", dest="until_date", help="YYYY-MM-DD")
    parser.add_argument("--session-from", type=int)
    parser.add_argument("--session-to", type=int)
    parser.add_argument("--limit-meetings", type=int)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=10.0)
    parser.add_argument("--checkpoint-every", type=int, default=50)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--errors-file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def has_search_scope(params: dict[str, str | int]) -> bool:
    return any(
        key in params
        for key in ("nameOfHouse", "from", "until", "sessionFrom", "sessionTo", "nameOfMeeting")
    )


def make_fetcher(args: argparse.Namespace) -> Callable[[str, dict[str, str | int]], dict[str, Any]]:
    def _fetch(path: str, params: dict[str, str | int]) -> dict[str, Any]:
        return fetch_json(
            path,
            params,
            retries=args.retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )

    return _fetch


def run_fetch(
    args: argparse.Namespace,
    fetcher: Callable[[str, dict[str, str | int]], dict[str, Any]] | None = None,
) -> FetchStats:
    scopes = build_search_scopes(args)
    if not any(has_search_scope(scope) for scope in scopes):
        raise SystemExit("Specify at least one search scope, such as --session-from/--session-to.")

    args.output.mkdir(parents=True, exist_ok=True)
    state_path = args.state_file or args.output / FETCH_STATE_FILENAME
    errors_path = args.errors_file or args.output / FETCH_ERRORS_FILENAME
    state = load_fetch_state(state_path)
    completed = set(str(issue_id) for issue_id in state.get("completed_issue_ids", []))
    fetch = fetcher or make_fetcher(args)
    stats = FetchStats()
    run_record: dict[str, Any] = {
        "started_at": utc_now(),
        "scopes": scopes,
        "stats": asdict(stats),
    }

    stop = False
    for scope in scopes:
        for issue_id in iter_issue_ids(scope, fetcher=fetch, delay_seconds=args.delay_seconds):
            if args.limit_meetings is not None and stats.fetched >= args.limit_meetings:
                stop = True
                break
            stats.discovered += 1
            path = issue_path(args.output, issue_id)
            if not args.overwrite and (issue_id in completed or path.exists()):
                completed.add(issue_id)
                stats.skipped += 1
                continue
            try:
                meeting = fetch_meeting(issue_id, fetcher=fetch)
                if meeting is None:
                    raise RuntimeError("meeting endpoint returned no meetingRecord")
                path = write_meeting(args.output, meeting, overwrite=args.overwrite)
                completed.add(issue_id)
                stats.fetched += 1
                print(f"Wrote {path}")
            except RuntimeError as exc:
                stats.failed += 1
                append_fetch_error(
                    errors_path,
                    {
                        "failed_at": utc_now(),
                        "issue_id": issue_id,
                        "scope": scope,
                        "error": str(exc),
                    },
                )
                print(f"FAILED {issue_id}: {exc}")
            if (
                args.checkpoint_every
                and (stats.fetched + stats.skipped + stats.failed) % args.checkpoint_every == 0
            ):
                state["completed_issue_ids"] = sorted(completed)
                run_record["stats"] = asdict(stats)
                state["latest_run"] = run_record
                save_fetch_state(state_path, state)
            if args.delay_seconds > 0:
                time.sleep(args.delay_seconds)
        if stop:
            break

    state["completed_issue_ids"] = sorted(completed)
    run_record["finished_at"] = utc_now()
    run_record["stats"] = asdict(stats)
    state["latest_run"] = run_record
    state["runs"] = [*state.get("runs", []), run_record][-20:]
    save_fetch_state(state_path, state)
    print(
        "Diet fetch complete: "
        f"discovered={stats.discovered} fetched={stats.fetched} "
        f"skipped={stats.skipped} failed={stats.failed} output={args.output}"
    )
    return stats


def main() -> None:
    run_fetch(parse_args())


if __name__ == "__main__":
    main()
