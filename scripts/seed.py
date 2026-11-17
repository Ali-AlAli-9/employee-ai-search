"""Seed a running API with the sample documents and run a demo query.

Usage:
    py -3 scripts/seed.py                     # assumes http://localhost:8000
    py -3 scripts/seed.py --base-url https://my-api.onrender.com --api-key secret
    py -3 scripts/seed.py --query "How many annual leave days do employees get?"

Uses only the standard library, so it works before any pip install.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ALLOWED = {".pdf", ".docx", ".txt", ".md", ".markdown"}
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "sample-data"


def request(
    method: str,
    url: str,
    api_key: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> tuple[int, dict]:
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw.decode("utf-8", "replace")}
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {url}: {exc.reason}") from exc


def multipart(field: str, path: Path) -> tuple[bytes, str]:
    boundary = f"----eais{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def wait_until_ready(base: str, api_key: str, document_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    delay = 0.5
    while time.monotonic() < deadline:
        status, document = request("GET", f"{base}/api/v1/documents/{document_id}", api_key)
        if status != 200:
            return {"status": f"http_{status}", "error_message": document.get("detail")}
        if document.get("status") in {"completed", "failed"}:
            return document
        time.sleep(delay)
        delay = min(delay * 1.5, 3.0)
    return {"status": "timeout", "error_message": "ingestion did not finish in time"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Employee AI Search Platform")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="dev-admin-key")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--query", default="How many annual leave days do employees get?")
    parser.add_argument("--no-wait", action="store_true", help="do not poll ingestion status")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    files = sorted(p for p in args.dir.glob("*") if p.suffix.lower() in ALLOWED)
    if not files:
        print(f"No supported files found in {args.dir}", file=sys.stderr)
        return 1

    try:
        status, health = request("GET", f"{base}/api/v1/health", args.api_key)
        print(f"health: {health.get('status', status)}")
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    uploaded: list[str] = []
    for path in files:
        body, content_type = multipart("file", path)
        status, payload = request(
            "POST", f"{base}/api/v1/documents/upload", args.api_key,
            body=body, content_type=content_type,
        )
        if status != 202:
            print(f"  x {path.name}: {status} {payload}", file=sys.stderr)
            continue
        document_id = payload["document_id"]
        uploaded.append(document_id)
        print(f"  + {path.name} ({path.stat().st_size:,} bytes) -> {document_id}")

    if not uploaded:
        return 1

    if not args.no_wait:
        for document_id in uploaded:
            document = wait_until_ready(base, args.api_key, document_id)
            state = document.get("status")
            marker = "ok" if state == "completed" else "x"
            extra = (
                f"{document.get('chunks_count', 0)} chunks"
                if state == "completed"
                else str(document.get("error_message") or "")
            )
            print(f"  {marker} {document.get('filename', document_id)}: {state} {extra}")

    if args.query:
        print(f"\nQ: {args.query}")
        status, payload = request(
            "POST",
            f"{base}/api/v1/chat",
            args.api_key,
            body=json.dumps({"message": args.query, "stream": False, "language": "en"}).encode(),
            content_type="application/json",
        )
        if status != 200:
            print(f"chat failed: {status} {payload}", file=sys.stderr)
            return 1
        print(f"A: {payload['answer']}")
        print(f"   confidence={payload['confidence']} latency={payload['latency_ms']}ms")
        for citation in payload.get("citations", []):
            page = f" p.{citation['page_number']}" if citation.get("page_number") else ""
            print(
                f"   [{citation['index']}] {citation['document_filename']}{page} "
                f"(score {citation['relevance_score']})"
            )
    return 0


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if __name__ == "__main__":
    raise SystemExit(main())
