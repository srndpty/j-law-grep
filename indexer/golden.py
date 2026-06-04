from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import django
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (BACKEND_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from search.service import SearchParams, SearchService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run golden query checks against OpenSearch")
    parser.add_argument(
        "--file", type=Path, default=PROJECT_ROOT / "tests" / "golden_queries" / "sample.json"
    )
    parser.add_argument("--size", type=int, default=10)
    parser.add_argument("--report", type=Path, help="Write per-case results as JSONL.")
    parser.add_argument("--markdown", type=Path, help="Write a compact Markdown summary.")
    return parser.parse_args()


def matches(hit: dict[str, Any], expected: dict[str, Any] | str) -> bool:
    if isinstance(expected, str):
        return expected in json.dumps(hit, ensure_ascii=False)
    return all(hit.get(key) == value for key, value in expected.items())


def run_case(
    service: SearchService, case: dict[str, Any], size: int
) -> tuple[list[str], dict[str, Any]]:
    query = case["query"]
    start = time.perf_counter()
    result = service.search(
        SearchParams(
            q=query,
            mode=case.get("mode", "literal"),
            filters=case.get("filters", {}),
            size=case.get("size", size),
            page=1,
        )
    )
    wall_ms = round((time.perf_counter() - start) * 1000)
    hits = result["hits"]
    failures: list[str] = []

    for expected in case.get("expected_top", []):
        if not hits or not matches(hits[0], expected):
            failures.append(f"{query!r}: top hit did not match {expected!r}")

    top_any = case.get("expected_top_any", [])
    if top_any and (not hits or not any(matches(hits[0], expected) for expected in top_any)):
        failures.append(f"{query!r}: top hit did not match any of {top_any!r}")

    for expected in case.get("expected_contains", []):
        if not any(matches(hit, expected) for hit in hits):
            failures.append(f"{query!r}: no hit matched {expected!r}")

    for expected in case.get("not_expected_contains", []):
        if any(matches(hit, expected) for hit in hits):
            failures.append(f"{query!r}: unexpected hit matched {expected!r}")

    total = int(result.get("total", 0))
    min_total = case.get("min_total")
    if min_total is not None and total < int(min_total):
        failures.append(f"{query!r}: total {total} was less than min_total {min_total}")

    max_wall_ms = case.get("max_wall_ms")
    if max_wall_ms is not None and wall_ms > int(max_wall_ms):
        failures.append(f"{query!r}: wall_ms {wall_ms} exceeded max_wall_ms {max_wall_ms}")

    top = hits[0] if hits else {}
    report = {
        "query": query,
        "mode": case.get("mode", "literal"),
        "ok": not failures,
        "total": total,
        "took_ms": result.get("took_ms", 0),
        "wall_ms": wall_ms,
        "top": {
            "law_id": top.get("law_id"),
            "law_name": top.get("law_name"),
            "article_no": top.get("article_no"),
            "paragraph_no": top.get("paragraph_no"),
            "item_no": top.get("item_no"),
        }
        if top
        else None,
        "index": result.get("index", {}).get("name"),
        "failures": failures,
    }
    return failures, report


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = sum(1 for row in rows if row["ok"])
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# Search Bench\n\nPassed: {ok} / {len(rows)}\n\n")
        fh.write("| ok | wall_ms | took_ms | total | mode | query | top |\n")
        fh.write("| -- | --: | --: | --: | -- | -- | -- |\n")
        for row in rows:
            top = row.get("top") or {}
            top_label = " ".join(
                str(part)
                for part in (top.get("law_name"), top.get("article_no"))
                if part not in (None, "")
            )
            fh.write(
                f"| {'yes' if row['ok'] else 'no'} | {row['wall_ms']} | {row['took_ms']} | "
                f"{row['total']} | {row['mode']} | {row['query']} | {top_label} |\n"
            )


def main() -> None:
    args = parse_args()
    with args.file.open("r", encoding="utf-8") as fh:
        cases = json.load(fh)

    service = SearchService()
    failures: list[str] = []
    reports: list[dict[str, Any]] = []
    for case in cases:
        case_failures, report = run_case(service, case, size=args.size)
        failures.extend(case_failures)
        reports.append(report)

    if args.report:
        write_jsonl(args.report, reports)
    if args.markdown:
        write_markdown(args.markdown, reports)

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Golden queries passed: {len(cases)}")


if __name__ == "__main__":
    main()
