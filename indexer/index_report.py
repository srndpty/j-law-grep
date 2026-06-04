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

from search.open_search_client import OpenSearchBackend  # noqa: E402


def build_report(alias: str) -> dict[str, Any]:
    backend = OpenSearchBackend(index=alias)
    concrete = backend.concrete_indices(alias)
    generations = backend.all_indices(f"{alias}-v*")
    stats = backend.index_stats(alias)
    return {
        "alias": alias,
        "concrete_indices": concrete,
        "schema_versions": backend.schema_versions(alias),
        "doc_count": backend.count(alias),
        "health": stats["health"],
        "old_generations": [index for index in generations if index not in concrete],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Print OpenSearch index report.")
    parser.add_argument("--alias", default=os.environ.get("OPENSEARCH_INDEX", "jlaw-current"))
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(args.alias)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with args.json_out.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
