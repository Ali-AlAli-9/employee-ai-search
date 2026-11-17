"""Show the PDF ``/PageLabels`` mapping the ingester will use.

Page-number inference from the page text was removed. This tool now only reports
the labels a PDF actually declares in its ``/PageLabels`` tree, which is exactly
what the ingestion pipeline stores as ``metadata.page_label``.

    py -3 scripts/inspect_page_labels.py "book.pdf"
    py -3 scripts/inspect_page_labels.py "book.pdf" --around 30

Nothing is uploaded or written.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pypdf import PdfReader  # noqa: E402

from app.ingestion import _pdf_page_labels  # noqa: E402


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        if line.strip():
            return line.strip()[:60]
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="path to the PDF file")
    parser.add_argument(
        "--around",
        type=int,
        default=0,
        help="only print rows near this physical page (default: all)",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=40,
        help="maximum rows to print (default: 40)",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    content = Path(args.pdf).read_bytes()
    reader = PdfReader(io.BytesIO(content))
    labels = _pdf_page_labels(reader)

    rows = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one bad page is not fatal
            print(f"warning: page {index} failed to extract: {exc}")
            text = ""
        label = labels[index - 1] if index <= len(labels) else None
        if label == str(index):
            # Matches the physical page: the ingester drops it.
            label = None
        if not text.strip():
            continue
        if args.around and abs(index - args.around) > 6:
            continue
        rows.append((index, label, _first_line(text)))

    print(f"file: {args.pdf}")
    print(f"physical pages: {len(reader.pages)}")
    print(f"/PageLabels entries: {len(labels)}")
    if labels:
        print(f"  first: {labels[:5]}")
    else:
        print("  no /PageLabels tree: citations will use the physical PDF page.")

    print()
    print(f"{'physical':>8}  {'label':>7}  first line")
    for index, label, first in rows[: args.rows]:
        print(f"{index:>8}  {label or '-':>7}  {first}")
    if len(rows) > args.rows:
        print(f"... {len(rows) - args.rows} more pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
