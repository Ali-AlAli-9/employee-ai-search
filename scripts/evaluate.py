#!/usr/bin/env python3
"""Retrieval + answer evaluation harness.

Runs a golden question set against a live API and reports:

* hit@1 / hit@3 / hit@5 and MRR of the retrieval stage
* whether the returned citations contain the expected fact
* whether the answer contains the expected fact
* abstention accuracy on questions the corpus cannot answer

Standard library only, so it runs anywhere the demo runs.

    py -3 scripts/evaluate.py
    py -3 scripts/evaluate.py --base-url https://<api>.onrender.com --api-key <key>
    py -3 scripts/evaluate.py --questions eval/thesis-questions.json --out eval/results.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

MARKS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
NO_ANSWER = ("لم أجد معلومات ذات صلة", "couldn't find relevant information")


def normalize(text: str) -> str:
    text = MARKS.sub("", text or "")
    text = (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
        .replace("ة", "ه")
    )
    text = text.replace("‎", " ").replace("‏", " ")
    return re.sub(r"\s+", " ", text.lower()).strip()


def contains_any(text: str, terms: list[str]) -> bool:
    haystack = normalize(text)
    return any(normalize(term) in haystack for term in terms)


def post(base_url: str, path: str, api_key: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{path} failed: HTTP {error.code} {error.read()[:300]!r}") from error


def evaluate(question: dict, base_url: str, api_key: str, top_k: int) -> dict:
    search = post(
        base_url, "/api/v1/search", api_key, {"query": question["question"], "top_k": top_k}
    )
    chat = post(
        base_url,
        "/api/v1/chat",
        api_key,
        {"message": question["question"], "stream": False, "language": question.get("language", "en")},
    )

    chunks = search.get("results", [])
    answer = chat.get("answer", "")
    citations = chat.get("citations", [])
    unanswerable = bool(question.get("unanswerable"))
    terms = question.get("retrieval_terms", [])
    answer_terms = question.get("answer_terms", [])

    rank = None
    for position, chunk in enumerate(chunks, start=1):
        if contains_any(chunk.get("text", ""), terms):
            rank = position
            break

    abstained = any(marker in answer for marker in NO_ANSWER)
    citation_hit = any(
        contains_any(citation.get("text_snippet", ""), terms) for citation in citations
    )

    return {
        "id": question["id"],
        "question": question["question"],
        "unanswerable": unanswerable,
        "retrieved": len(chunks),
        "rank": rank,
        "hit1": rank == 1,
        "hit3": rank is not None and rank <= 3,
        "hit5": rank is not None and rank <= 5,
        "mrr": 0.0 if rank is None else 1.0 / rank,
        "citation_hit": citation_hit,
        "abstained": abstained,
        "answer": answer,
        "confidence": chat.get("confidence", 0.0),
        "answer_ok": (
            abstained if unanswerable else (not abstained and contains_any(answer, answer_terms))
        ),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="dev-admin-key")
    parser.add_argument(
        "--questions",
        default=str(pathlib.Path(__file__).resolve().parent.parent / "eval" / "thesis-questions.json"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    suite = json.loads(pathlib.Path(args.questions).read_text(encoding="utf-8"))
    results = [evaluate(q, args.base_url, args.api_key, args.top_k) for q in suite["questions"]]

    answerable = [r for r in results if not r["unanswerable"]]
    unanswerable = [r for r in results if r["unanswerable"]]

    print(f"\n{suite.get('name', 'evaluation')}")
    print(f"{'id':<5} {'ret':>3} {'rank':>4} {'cit':>4} {'abs':>4} {'ok':>4}  question")
    for row in results:
        rank = "-" if row["rank"] is None else str(row["rank"])
        print(
            f"{row['id']:<5} {row['retrieved']:>3} {rank:>4} "
            f"{'yes' if row['citation_hit'] else 'no':>4} "
            f"{'yes' if row['abstained'] else 'no':>4} "
            f"{'yes' if row['answer_ok'] else 'no':>4}  {row['question'][:60]}"
        )

    def rate(rows, key):
        return (sum(1 for row in rows if row[key]) / len(rows)) if rows else 0.0

    print("\n--- retrieval (answerable questions) ---")
    print(f"hit@1 {rate(answerable, 'hit1'):.3f}   hit@3 {rate(answerable, 'hit3'):.3f}   "
          f"hit@{args.top_k} {rate(answerable, 'hit5'):.3f}   "
          f"MRR {sum(r['mrr'] for r in answerable) / max(1, len(answerable)):.3f}")
    answered = sum(1 for row in answerable if not row["abstained"]) / max(1, len(answerable))
    print(f"citation hit {rate(answerable, 'citation_hit'):.3f}   "
          f"answer accuracy {rate(answerable, 'answer_ok'):.3f}   "
          f"answered {answered:.3f}")
    print("--- abstention (unanswerable questions) ---")
    print(f"abstention accuracy {rate(unanswerable, 'abstained'):.3f} "
          f"({len(unanswerable)} questions)")

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"suite": suite.get("name"), "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nresults written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
