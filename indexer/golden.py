from __future__ import annotations

import argparse
import json
import os
import sys
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
    return parser.parse_args()


def matches(hit: dict[str, Any], expected: dict[str, Any] | str) -> bool:
    if isinstance(expected, str):
        return expected in json.dumps(hit, ensure_ascii=False)
    return all(hit.get(key) == value for key, value in expected.items())


def run_case(service: SearchService, case: dict[str, Any], size: int) -> list[str]:
    query = case["query"]
    result = service.search(
        SearchParams(
            q=query,
            mode=case.get("mode", "literal"),
            filters=case.get("filters", {}),
            size=case.get("size", size),
            page=1,
        )
    )
    hits = result["hits"]
    failures: list[str] = []

    for expected in case.get("expected_top", []):
        if not hits or not matches(hits[0], expected):
            failures.append(f"{query!r}: top hit did not match {expected!r}")

    for expected in case.get("expected_contains", []):
        if not any(matches(hit, expected) for hit in hits):
            failures.append(f"{query!r}: no hit matched {expected!r}")

    for expected in case.get("not_expected_contains", []):
        if any(matches(hit, expected) for hit in hits):
            failures.append(f"{query!r}: unexpected hit matched {expected!r}")

    return failures


def main() -> None:
    args = parse_args()
    with args.file.open("r", encoding="utf-8") as fh:
        cases = json.load(fh)

    service = SearchService()
    failures: list[str] = []
    for case in cases:
        failures.extend(run_case(service, case, size=args.size))

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Golden queries passed: {len(cases)}")


if __name__ == "__main__":
    main()
