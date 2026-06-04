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


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollback alias to an existing versioned index.")
    parser.add_argument("--alias", default=os.environ.get("OPENSEARCH_INDEX", "jlaw-current"))
    parser.add_argument("--to", required=True, help="Concrete target index.")
    args = parser.parse_args()

    backend = OpenSearchBackend(index=args.alias)
    backend.validate_schema(args.to)
    backend.switch_alias(args.alias, args.to)
    print(f"Switched alias {args.alias} -> {args.to}")


if __name__ == "__main__":
    main()
