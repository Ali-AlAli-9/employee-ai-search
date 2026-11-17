"""Read-only check that document rows, chunk rows and vectors agree.

Usage:
    py -3 scripts/verify_consistency.py
    py -3 scripts/verify_consistency.py --stale-minutes 10 --json

Exit status 0 means consistent; 1 means at least one check failed or could not
run. Nothing is ever modified. Run with the same DATA_DIR / DATABASE_URL /
QDRANT_URL as the API being inspected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import consistency, db  # noqa: E402


def _label(item: object) -> str:
    """Human output stays short: ids only, never document text."""
    if isinstance(item, dict):
        return str(item.get("id", ""))
    return str(item)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify index consistency (read-only)")
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=30,
        help="processing rows older than this are reported as stale",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args()

    db.init_db()
    report = consistency.inspect(stale_minutes=args.stale_minutes).as_dict()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"consistent: {report['ok']}")
        for name in (
            "count_mismatches",
            "orphan_chunks",
            "orphan_vectors",
            "missing_vectors",
            "stale_processing",
        ):
            items = report[name]
            print(f"{name}: {len(items)}")
            for item in items[:10]:
                print(f"  - {_label(item)}")
        if report["vector_store_error"]:
            print(f"vector_store_error: {report['vector_store_error']}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
