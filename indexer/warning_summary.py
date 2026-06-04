from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_warnings(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Warning file not found: {path}")
    warnings: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                warnings.append(json.loads(line))
    return warnings


def summarize(warnings: list[dict[str, Any]]) -> dict[str, Any]:
    by_code = Counter(str(item.get("code", "unknown")) for item in warnings)
    by_law = Counter(str(item.get("law_id", "")) for item in warnings if item.get("law_id"))
    return {
        "total": len(warnings),
        "by_code": dict(sorted(by_code.items())),
        "top_affected_laws": by_law.most_common(20),
    }


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)


def print_summary(summary: dict[str, Any]) -> None:
    print(f"total: {summary['total']}")
    for code, count in summary["by_code"].items():
        print(f"{code}: {count}")
    if summary["top_affected_laws"]:
        print("\nTop affected laws:")
        for law_id, count in summary["top_affected_laws"]:
            print(f"- {law_id}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize importer warning JSONL.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    summary = summarize(load_warnings(args.path))
    print_summary(summary)
    if args.json_out:
        write_summary(args.json_out, summary)


if __name__ == "__main__":
    main()
