from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an OpenSearch index against a corpus manifest")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "indexer" / "data" / "manifest.json")
    parser.add_argument("--index", default=os.environ.get("OPENSEARCH_INDEX", "jlaw-current"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.manifest.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    expected = int(manifest["counts"]["records"])

    backend = OpenSearchBackend(index=args.index)
    actual = backend.count()
    concrete = backend.indices_for_alias(args.index) or [args.index]

    print(f"index: {args.index}")
    print(f"concrete: {', '.join(concrete)}")
    print(f"expected_records: {expected}")
    print(f"actual_records: {actual}")
    if actual != expected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
