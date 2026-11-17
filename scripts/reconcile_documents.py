"""Repair a document index that verifier reported as inconsistent.

Dry-run by default. Pass ``--apply`` to write, and ``--purge-orphans`` to delete
orphan chunk rows and orphan vectors; without it only stale ``processing`` rows
are marked ``failed`` so an operator can delete and re-upload them.

Usage:
    py -3 scripts/reconcile_documents.py
    py -3 scripts/reconcile_documents.py --apply
    py -3 scripts/reconcile_documents.py --apply --purge-orphans --json

Run with the same DATA_DIR / DATABASE_URL / QDRANT_URL as the API. The command
never re-uploads a file and never invents a vector for a missing chunk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import consistency, db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile document index (dry-run first)")
    parser.add_argument("--apply", action="store_true", help="actually perform the repairs")
    parser.add_argument(
        "--purge-orphans",
        action="store_true",
        help="delete orphan chunk rows and orphan vectors (only with --apply)",
    )
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = parser.parse_args()

    if args.purge_orphans and not args.apply:
        parser.error("--purge-orphans requires --apply")

    db.init_db()
    plan = consistency.reconcile(
        apply=args.apply,
        stale_minutes=args.stale_minutes,
        purge_orphans=args.purge_orphans,
    )

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        mode = "APPLIED" if plan["applied"] else "DRY RUN"
        print(f"mode: {mode}")
        print(f"stale processing -> failed: {len(plan['stale_to_fail'])}")
        print(f"orphan chunks: {len(plan['orphan_chunks'])}")
        print(f"orphan vectors: {len(plan['orphan_vectors'])}")
        print(f"missing vectors (re-upload needed): {len(plan['missing_vectors'])}")
        if plan["applied"]:
            print(f"purged chunks: {plan['purged_chunks']}")
            print(f"purged vectors: {plan['purged_vectors']}")
        if plan["vector_store_error"]:
            print(f"vector_store_error: {plan['vector_store_error']}", file=sys.stderr)
    return 1 if plan["vector_store_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
