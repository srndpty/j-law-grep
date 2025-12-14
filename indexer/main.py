from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # Put project root on sys.path so `backend` package can be imported
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from search.open_search_client import OpenSearchBackend  # noqa: E402

from .pipeline import collect_records, to_index_actions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index sample Japanese law corpus")
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "indexer" / "sample_corpus")
    parser.add_argument("--provider", choices=["opensearch"], default="opensearch")
    return parser.parse_args()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    args = parse_args()

    backend = OpenSearchBackend()
    backend.ensure_index()

    records = collect_records(args.input)
    actions = to_index_actions(records)
    backend.bulk(actions)

    print(f"Indexed {len(actions)} records into {backend.index}")


if __name__ == "__main__":
    main()
