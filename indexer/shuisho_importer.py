"""質問主意書・答弁書のコーパス取得。

衆参両院とも公式 API が無いため HTML をスクレイピングする。URL 体系は会期と
提出番号で完全に決まるので、会期一覧ページから提出番号とリンクを拾い、質問本文
と答弁本文の HTML をそれぞれ取得する。

  python -m indexer.shuisho_importer --output indexer/shuisho_data \
      --house both --session-from 213 --session-to 221
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from indexer.utils import normalize_text

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "indexer" / "shuisho_data"
USER_AGENT = "j-law-grep/0.1 (+https://github.com/srndpty/j-law-grep)"
FETCH_STATE_FILENAME = "_fetch_state.json"
FETCH_ERRORS_FILENAME = "_fetch_errors.jsonl"

SHUGIIN_BASE_URL = "https://www.shugiin.go.jp/internet/itdb_shitsumon.nsf/html/shitsumon/"
SANGIIN_BASE_URL = "https://www.sangiin.go.jp/japanese/joho1/kousei/syuisyo/"
HOUSE_NAMES = {"shugiin": "衆議院", "sangiin": "参議院"}

TAG_PATTERN = re.compile(r"<[^>]*>")
BR_PATTERN = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
HR_PATTERN = re.compile(r"<\s*hr[^>]*>", re.IGNORECASE)
CHARSET_PATTERN = re.compile(rb"charset\s*=\s*[\"']?([\w-]+)", re.IGNORECASE)
# 本文の終端候補。衆院は末尾のナビ DIV、参院は本文を包む TD が閉じる。
BODY_END_PATTERN = re.compile(
    r"<\s*div\s+class=\"gh2|<\s*/\s*td\s*>|<\s*/\s*table\s*>|<\s*div\s+id=\"Footer",
    re.IGNORECASE,
)
CABINET_NUMBER_PATTERN = re.compile(r"内閣[衆参]質[^<\s]*第[^<\s]*号")
ANSWERER_PATTERN = re.compile(r"(内閣総理大臣[^<]*)")
ERA_DATE_PATTERN = re.compile(
    r"(令和|平成|昭和|大正|明治)([^年]{1,4})年([^月]{1,3})月([^日]{1,3})日"
)
ERA_START_YEARS = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
KANJI_DIGITS = {
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


class HttpNotFound(RuntimeError):
    """存在しない会期 / 本文ページ。リトライせずスキップする。"""


@dataclass
class FetchStats:
    discovered: int = 0
    fetched: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class ListEntry:
    house_code: str
    session: int
    number: int
    title: str = ""
    submitter: str = ""
    status: str = ""
    progress_url: str = ""
    question_url: str = ""
    question_pdf_url: str = ""
    answer_url: str = ""
    answer_pdf_url: str = ""

    @property
    def shuisho_id(self) -> str:
        return f"{self.house_code}-{self.session}-{self.number:03d}"


@dataclass
class BodyDoc:
    paragraphs: list[str] = field(default_factory=list)
    date: str = ""
    answerer: str = ""
    cabinet_number: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kanji_to_int(value: str) -> int | None:
    """「二十四」「元」「十」などの漢数字を整数に。想定外の文字が混ざれば None。"""
    value = value.strip()
    if not value:
        return None
    if value == "元":
        return 1
    if value.isdigit():
        return int(value)
    if any(char not in KANJI_DIGITS and char != "十" for char in value):
        return None
    if "十" not in value:
        total = 0
        for char in value:
            total = total * 10 + KANJI_DIGITS[char]
        return total
    tens, _, ones = value.partition("十")
    tens_value = KANJI_DIGITS[tens] if tens else 1
    ones_value = 0
    for char in ones:
        ones_value = ones_value * 10 + KANJI_DIGITS[char]
    return tens_value * 10 + ones_value


def wareki_to_iso(text: str) -> str:
    """「令和七年二月四日」を含む文字列から最初の日付を ISO 形式で返す。"""
    match = ERA_DATE_PATTERN.search(text)
    if not match:
        return ""
    era, year_text, month_text, day_text = match.groups()
    year = kanji_to_int(year_text)
    month = kanji_to_int(month_text)
    day = kanji_to_int(day_text)
    if year is None or month is None or day is None:
        return ""
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{ERA_START_YEARS[era] + year:04d}-{month:02d}-{day:02d}"


def decode_html(raw: bytes) -> str:
    """meta charset を見て Shift_JIS (衆院) / UTF-8 (参院) を判別する。"""
    match = CHARSET_PATTERN.search(raw[:2048])
    declared = match.group(1).decode("ascii", errors="ignore").lower() if match else ""
    candidates = [declared] if declared else []
    candidates += ["utf-8", "cp932"]
    for encoding in candidates:
        # Shift_JIS は cp932 として読むほうが機種依存文字に強い。
        name = "cp932" if encoding in {"shift_jis", "shift-jis", "sjis"} else encoding
        try:
            return raw.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_html_once(url: str, timeout: int = 60) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - official public site
            raw = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise HttpNotFound(f"HTTP 404: {url}") from exc
        raise RuntimeError(f"HTTP error {exc.code} {exc.reason}: {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed: {exc.reason} ({url})") from exc
    return decode_html(raw)


def fetch_html(
    url: str,
    timeout: int = 60,
    retries: int = 3,
    retry_backoff_seconds: float = 10.0,
) -> str:
    last_error: RuntimeError | None = None
    for attempt in range(retries + 1):
        try:
            return fetch_html_once(url, timeout=timeout)
        except HttpNotFound:
            raise
        except RuntimeError as exc:
            last_error = exc
            if attempt >= retries:
                break
            if retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds * (attempt + 1))
    assert last_error is not None
    raise last_error


def strip_tags(html: str) -> str:
    return normalize_text(TAG_PATTERN.sub("", html))


def split_paragraphs(html: str) -> list[str]:
    """<BR> 区切りの平文を段落リストに。空行は落とす。"""
    text = BR_PATTERN.sub("\n", html)
    text = TAG_PATTERN.sub("", text)
    paragraphs = [normalize_text(line) for line in text.split("\n")]
    return [paragraph for paragraph in paragraphs if paragraph]


def content_region(html: str) -> str:
    """ヘッダ・ナビを落とした本文領域。衆院と参院で入口のマーカーが違う。"""
    for marker in ('id="TopContents"', 'id="ContentsBox"'):
        index = html.find(marker)
        if index != -1:
            return html[index:]
    return html


def parse_body(html: str) -> BodyDoc:
    """質問本文 / 答弁本文ページを段落と付随メタに分解する。"""
    region = content_region(html)
    split = HR_PATTERN.search(region)
    if split is None:
        return BodyDoc()
    header = region[: split.start()]
    body = region[split.end() :]
    end = BODY_END_PATTERN.search(body)
    if end is not None:
        body = body[: end.start()]

    header_text = strip_tags(header)
    answerer_match = ANSWERER_PATTERN.search(header)
    cabinet_match = CABINET_NUMBER_PATTERN.search(header_text)
    return BodyDoc(
        paragraphs=split_paragraphs(body),
        date=wareki_to_iso(header_text),
        answerer=normalize_text(answerer_match.group(1)) if answerer_match else "",
        cabinet_number=cabinet_match.group(0) if cabinet_match else "",
    )


def shugiin_list_url(session: int) -> str:
    return f"{SHUGIIN_BASE_URL}kaiji{session}_l.htm"


def sangiin_list_url(session: int) -> str:
    return f"{SANGIIN_BASE_URL}{session}/syuisyo.htm"


def list_url(house_code: str, session: int) -> str:
    return shugiin_list_url(session) if house_code == "shugiin" else sangiin_list_url(session)


def _first_href(html: str) -> str:
    match = re.search(r'href\s*=\s*"([^"]+)"', html, re.IGNORECASE)
    return match.group(1) if match else ""


def parse_shugiin_list(html: str, session: int, base_url: str) -> list[ListEntry]:
    """衆院の一覧表。各セルが headers="SHITSUMON.*" を持つので列を取り違えない。"""
    entries: list[ListEntry] = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        cells = {
            name.upper(): value
            for name, value in re.findall(
                r'(?is)<td[^>]*headers="SHITSUMON\.([A-Z]+)"[^>]*>(.*?)</td>', row
            )
        }
        number = kanji_to_int(strip_tags(cells.get("NUMBER", "")))
        if number is None:
            continue
        entry = ListEntry(house_code="shugiin", session=session, number=number)
        entry.title = strip_tags(cells.get("KENMEI", ""))
        entry.submitter = strip_tags(cells.get("TEISHUTSUSHA", "")).removesuffix("君")
        entry.status = strip_tags(cells.get("STATUS", ""))
        for key, attribute in (
            ("KLINK", "progress_url"),
            ("SLINK", "question_url"),
            ("SLINKPDF", "question_pdf_url"),
            ("TLINK", "answer_url"),
            ("TLINKPDF", "answer_pdf_url"),
        ):
            href = _first_href(cells.get(key, ""))
            if href:
                setattr(entry, attribute, urljoin(base_url, href))
        entries.append(entry)
    return entries


def parse_sangiin_list(html: str, session: int, base_url: str) -> list[ListEntry]:
    """参院の一覧表。件名リンク (meisai/m{会期}{番号}.htm) を件のアンカーにする。"""
    entries: list[ListEntry] = []
    matches = list(
        re.finditer(
            rf'(?is)<a\s+href="(meisai/m{session}(\d+)\.htm)"[^>]*>(.*?)</a>',
            html,
        )
    )
    for index, match in enumerate(matches):
        number = int(match.group(2))
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        segment = html[match.end() : segment_end]
        entry = ListEntry(house_code="sangiin", session=session, number=number)
        entry.title = strip_tags(match.group(3))
        entry.progress_url = urljoin(base_url, match.group(1))
        submitter = re.search(r'(?is)<td[^>]*rowspan="2"[^>]*class="ta_l"[^>]*>(.*?)</td>', segment)
        if submitter:
            entry.submitter = strip_tags(submitter.group(1)).replace(" ", "").removesuffix("君")
        for pattern, attribute in (
            (rf"syuh/s{session}{number:03d}\.htm", "question_url"),
            (rf"syup/s{session}{number:03d}\.pdf", "question_pdf_url"),
            (rf"touh/t{session}{number:03d}\.htm", "answer_url"),
            (rf"toup/t{session}{number:03d}\.pdf", "answer_pdf_url"),
        ):
            link = re.search(pattern, segment)
            if link:
                setattr(entry, attribute, urljoin(base_url, link.group(0)))
        entries.append(entry)
    return entries


def parse_list(house_code: str, html: str, session: int, base_url: str) -> list[ListEntry]:
    if house_code == "shugiin":
        return parse_shugiin_list(html, session, base_url)
    return parse_sangiin_list(html, session, base_url)


def build_document(entry: ListEntry, question: BodyDoc | None, answer: BodyDoc | None) -> dict:
    document: dict[str, Any] = {
        "source_type": "shuisho",
        "shuisho_id": entry.shuisho_id,
        "house": HOUSE_NAMES[entry.house_code],
        "session": str(entry.session),
        "number": str(entry.number),
        "title": entry.title,
        "submitter": entry.submitter,
        "status": entry.status,
        "progress_url": entry.progress_url,
        "question": None,
        "answer": None,
    }
    if question and question.paragraphs:
        document["question"] = {
            "url": entry.question_url,
            "pdf_url": entry.question_pdf_url,
            "date": question.date,
            "paragraphs": question.paragraphs,
        }
    if answer and answer.paragraphs:
        document["answer"] = {
            "url": entry.answer_url,
            "pdf_url": entry.answer_pdf_url,
            "date": answer.date,
            "answerer": answer.answerer,
            "cabinet_number": answer.cabinet_number,
            "paragraphs": answer.paragraphs,
        }
    return document


def document_path(output_dir: Path, entry: ListEntry) -> Path:
    return output_dir / f"{entry.shuisho_id}.json"


def write_document(output_dir: Path, entry: ListEntry, document: dict) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = document_path(output_dir, entry)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def load_fetch_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "completed_ids": [], "runs": []}
    with path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)
    state.setdefault("completed_ids", [])
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


def houses_for(house: str) -> list[str]:
    return ["shugiin", "sangiin"] if house == "both" else [house]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch written questions and cabinet answers")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--house", choices=["shugiin", "sangiin", "both"], default="both")
    parser.add_argument("--session-from", type=int, required=True)
    parser.add_argument("--session-to", type=int, required=True)
    parser.add_argument(
        "--limit-discovered",
        type=int,
        help="Stop after discovering this many entries (counts skipped + fetched + failed).",
    )
    parser.add_argument(
        "--limit-fetched",
        type=int,
        help="Stop after fetching this many new entries (skips do not count).",
    )
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=10.0)
    parser.add_argument("--checkpoint-every", type=int, default=50)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--errors-file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def make_fetcher(args: argparse.Namespace) -> Callable[[str], str]:
    def _fetch(url: str) -> str:
        return fetch_html(
            url,
            retries=args.retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )

    return _fetch


def iter_entries(
    houses: list[str],
    session_from: int,
    session_to: int,
    fetcher: Callable[[str], str],
    delay_seconds: float = 3.0,
    on_missing: Callable[[str, int, str], None] | None = None,
) -> Iterator[ListEntry]:
    """会期番号を機械的に走査する。一覧ページが無い会期 (404) はスキップ。"""
    for house_code in houses:
        for session in range(session_from, session_to + 1):
            url = list_url(house_code, session)
            try:
                html = fetcher(url)
            except HttpNotFound:
                if on_missing:
                    on_missing(house_code, session, "list page not found")
                html = ""
            except RuntimeError as exc:
                if on_missing:
                    on_missing(house_code, session, str(exc))
                html = ""
            if html:
                yield from parse_list(house_code, html, session, url)
            # 空振りの会期でも礼儀としてディレイを挟む。
            if delay_seconds > 0:
                time.sleep(delay_seconds)


def fetch_entry_bodies(
    entry: ListEntry,
    fetcher: Callable[[str], str],
    delay_seconds: float = 3.0,
) -> tuple[BodyDoc | None, BodyDoc | None]:
    question: BodyDoc | None = None
    answer: BodyDoc | None = None
    for url, assign in ((entry.question_url, "question"), (entry.answer_url, "answer")):
        if not url:
            continue
        try:
            body = parse_body(fetcher(url))
        except HttpNotFound:
            body = None
        if assign == "question":
            question = body
        else:
            answer = body
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    return question, answer


def run_fetch(
    args: argparse.Namespace,
    fetcher: Callable[[str], str] | None = None,
) -> FetchStats:
    args.output.mkdir(parents=True, exist_ok=True)
    state_path = args.state_file or args.output / FETCH_STATE_FILENAME
    errors_path = args.errors_file or args.output / FETCH_ERRORS_FILENAME
    state = load_fetch_state(state_path)
    completed = {str(item) for item in state.get("completed_ids", [])}
    fetch = fetcher or make_fetcher(args)
    stats = FetchStats()
    houses = houses_for(args.house)
    run_record: dict[str, Any] = {
        "started_at": utc_now(),
        "houses": houses,
        "session_from": args.session_from,
        "session_to": args.session_to,
        "stats": asdict(stats),
    }

    def record_missing(house_code: str, session: int, reason: str) -> None:
        append_fetch_error(
            errors_path,
            {
                "failed_at": utc_now(),
                "house": house_code,
                "session": session,
                "error": reason,
            },
        )

    entries = iter_entries(
        houses,
        args.session_from,
        args.session_to,
        fetcher=fetch,
        delay_seconds=args.delay_seconds,
        on_missing=record_missing,
    )
    for entry in entries:
        if args.limit_fetched is not None and stats.fetched >= args.limit_fetched:
            break
        if args.limit_discovered is not None and stats.discovered >= args.limit_discovered:
            break
        stats.discovered += 1
        path = document_path(args.output, entry)
        if not args.overwrite and (entry.shuisho_id in completed or path.exists()):
            completed.add(entry.shuisho_id)
            stats.skipped += 1
            continue
        try:
            question, answer = fetch_entry_bodies(
                entry, fetcher=fetch, delay_seconds=args.delay_seconds
            )
            document = build_document(entry, question, answer)
            # HTML 本文が一切取れない件は PDF 専用等。警告だけ残して先へ進む。
            if document["question"] is None and document["answer"] is None:
                raise RuntimeError("no HTML body available")
            path = write_document(args.output, entry, document)
            completed.add(entry.shuisho_id)
            stats.fetched += 1
            print(f"Wrote {path}")
        except RuntimeError as exc:
            stats.failed += 1
            append_fetch_error(
                errors_path,
                {
                    "failed_at": utc_now(),
                    "shuisho_id": entry.shuisho_id,
                    "question_url": entry.question_url,
                    "answer_url": entry.answer_url,
                    "error": str(exc),
                },
            )
            print(f"FAILED {entry.shuisho_id}: {exc}")
        processed = stats.fetched + stats.skipped + stats.failed
        if args.checkpoint_every and processed % args.checkpoint_every == 0:
            state["completed_ids"] = sorted(completed)
            run_record["stats"] = asdict(stats)
            state["latest_run"] = run_record
            save_fetch_state(state_path, state)

    state["completed_ids"] = sorted(completed)
    run_record["finished_at"] = utc_now()
    run_record["stats"] = asdict(stats)
    state["latest_run"] = run_record
    state["runs"] = [*state.get("runs", []), run_record][-20:]
    save_fetch_state(state_path, state)
    print(
        "Shuisho fetch complete: "
        f"discovered={stats.discovered} fetched={stats.fetched} "
        f"skipped={stats.skipped} failed={stats.failed} output={args.output}"
    )
    return stats


def main() -> None:
    run_fetch(parse_args())


if __name__ == "__main__":
    main()
