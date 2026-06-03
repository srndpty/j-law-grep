from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import django
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Ensure both project root and Django package root are on sys.path
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (BACKEND_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from search.open_search_client import OpenSearchBackend  # noqa: E402

from .manifest import build_manifest, write_manifest  # noqa: E402
from .pipeline import iter_records, to_index_actions  # noqa: E402


def versioned_index_name(alias: str) -> str:
    safe_alias = alias.replace("*", "").replace(",", "").replace(" ", "-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{safe_alias}-v{stamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index sample Japanese law corpus")
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "indexer" / "sample_corpus")
    parser.add_argument("--provider", choices=["opensearch"], default="opensearch")
    parser.add_argument(
        "--progress", action="store_true", help="Show progress while loading corpus"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=1000, help="Bulk chunk size (default: 1000)"
    )
    parser.add_argument(
        "--max-bulk-mb", type=int, default=None, help="Maximum bulk request size in MiB."
    )
    parser.add_argument("--index", help="Concrete index to write. Defaults to OPENSEARCH_INDEX.")
    parser.add_argument("--alias", help="Alias to switch after a successful versioned build.")
    parser.add_argument(
        "--versioned",
        action="store_true",
        help="Build a fresh versioned index and switch --alias to it.",
    )
    parser.add_argument(
        "--write-manifest", action="store_true", help="Write manifest.json before indexing."
    )
    parser.add_argument(
        "--forcemerge", action="store_true", help="Force merge the new index before alias switch."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.write_manifest:
        manifest_path = write_manifest(args.input, source="indexer")
        print(f"Wrote corpus manifest: {manifest_path}")

    manifest = build_manifest(args.input, source="indexer")
    expected_records = int(manifest["counts"]["records"])

    alias = args.alias or os.environ.get("OPENSEARCH_INDEX", "jlaw-current")
    target_index = args.index or (versioned_index_name(alias) if args.versioned else None)
    backend = OpenSearchBackend(index=target_index)

    if args.versioned:
        if not args.alias:
            raise SystemExit(
                "--versioned requires --alias so the new index can be promoted atomically."
            )
        backend.create_index(backend.index)
    else:
        backend.ensure_index()

    try:
        records = iter_records(args.input, show_progress=args.progress)
        actions = to_index_actions(records)
        max_chunk_bytes = args.max_bulk_mb * 1024 * 1024 if args.max_bulk_mb else None
        indexed = backend.bulk(
            actions,
            chunk_size=args.chunk_size,
            max_chunk_bytes=max_chunk_bytes,
            progress=args.progress,
        )

        print(f"Indexed {indexed} records into {backend.index}")
        if indexed != expected_records:
            raise RuntimeError(
                f"Indexed record count mismatch: expected {expected_records}, got {indexed}"
            )

        if args.versioned:
            backend.prepare_for_search(forcemerge=args.forcemerge)

        actual_count = backend.count()
        if actual_count != expected_records:
            raise RuntimeError(
                f"OpenSearch count mismatch: expected {expected_records}, got {actual_count}"
            )

        if args.versioned:
            backend.switch_alias(args.alias, backend.index)
            print(f"Switched alias {args.alias} -> {backend.index}")
    except Exception:
        if args.versioned:
            backend.delete_index(backend.index)
            print(f"Deleted failed versioned index: {backend.index}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
