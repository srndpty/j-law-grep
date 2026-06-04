from __future__ import annotations

import argparse
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


def cleanup(alias: str, keep: int, force: bool) -> list[str]:
    backend = OpenSearchBackend(index=alias)
    live = set(backend.indices_for_alias(alias))
    generations = [index for index in backend.all_indices(f"{alias}-v*") if index not in live]
    delete_candidates = generations[: max(len(generations) - keep, 0)]
    for index in delete_candidates:
        action = "DELETE" if force else "DRY-RUN delete"
        print(f"{action}: {index}")
        if force:
            backend.delete_index(index)
    return delete_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete old versioned OpenSearch indices.")
    parser.add_argument("--alias", default=os.environ.get("OPENSEARCH_INDEX", "jlaw-current"))
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cleanup(args.alias, args.keep, args.force)


if __name__ == "__main__":
    main()
