"""Numbered-heading detection for extracted documents.

DOCX text arrives as one paragraph per line and sections are numbered, e.g.
``3-5 تنفيذ مرحلة التعرف على الوجه`` (often with invisible RLM marks between the
digits). A question that *is* a section title must return that section's body,
not whichever paragraph shares the words "الوجه" and "التعرف" most often.

The helpers here are intentionally small and text-only: no document model, no
page assumptions. They work for any numbered outline (DOCX, PDF text, Markdown).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .embeddings import content_terms

# RLM/LRM and Arabic marks sit between the digits of DOCX headings ("‎3‎-‎5‎").
_MARKS_RE = re.compile(r"[\u200e\u200f\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
# "3-5 title", "3-5-1 title"; a dash is required so table rows ("1 | ...") and
# plain numbers ("20 معلماً") are not mistaken for headings.
_HEADING_RE = re.compile(r"^\s*([0-9]+(?:\s*-\s*[0-9]+)+)\s+(\S.*)$")
_CAPTION_RE = re.compile(r"^(الشكل|الجدول|Figure|Table)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"[0-9]+(?:\s*-\s*[0-9]+)*")
# Dotted leaders belong to a table of contents, never to a real heading.
_TOC_DOTTED_RE = re.compile(r"(?:\.\s*){3,}")


@dataclass(frozen=True)
class Heading:
    """A numbered heading found on one line of a chunk."""

    line: int
    number: str  # "3-5"
    title: str  # "تنفيذ مرحلة التعرف على الوجه"
    terms: frozenset[str]

    @property
    def parts(self) -> tuple[int, ...]:
        return tuple(int(part) for part in self.number.split("-"))

    @property
    def depth(self) -> int:
        return len(self.parts)


def clean_line(line: str) -> str:
    return _MARKS_RE.sub("", line or "").strip()


def is_caption(line: str) -> bool:
    """Figure/table captions are labels, never answers."""
    return bool(_CAPTION_RE.match(clean_line(line)))


def heading_of(line: str) -> Heading | None:
    """Parse one line as a numbered heading, or return ``None``."""
    cleaned = clean_line(line)
    if not cleaned or len(cleaned) > 140:
        return None
    if _TOC_DOTTED_RE.search(cleaned):
        return None
    match = _HEADING_RE.match(cleaned)
    if not match:
        return None
    number = re.sub(r"\s+", "", match.group(1))
    title = match.group(2).strip(" :.-–—")
    if not title:
        return None
    terms = frozenset(content_terms(title))
    if not terms:
        return None
    return Heading(line=0, number=number, title=title, terms=terms)


def headings(text: str) -> list[Heading]:
    """Every numbered heading line in ``text``, in document order."""
    found: list[Heading] = []
    for index, raw in enumerate(text.splitlines()):
        parsed = heading_of(raw)
        if parsed is None:
            continue
        found.append(
            Heading(line=index, number=parsed.number, title=parsed.title, terms=parsed.terms)
        )
    return found


def query_numbers(query: str) -> set[str]:
    """Section numbers written in the question ("3-5", "3-5-1")."""
    return {re.sub(r"\s+", "", match) for match in _NUMBER_RE.findall(clean_line(query))}


def section_lines(
    text: str,
    *,
    after: int | None = None,
    before: int | None = None,
    min_chars: int = 15,
) -> list[str]:
    """Prose lines that belong to a section body.

    ``after`` is the line of the heading that opens the section inside the chunk
    and ``before`` the line where the next section starts. The anchor chunk may
    carry the previous section in its first lines and a sibling chunk may carry
    the next section in its last ones; both must stay out. Heading, caption and
    table lines are dropped everywhere - a figure caption under a heading is not
    an answer.
    """
    lines = text.splitlines()
    begin = 0 if after is None else after + 1
    end = len(lines) if before is None else max(begin, before)
    body: list[str] = []
    for raw in lines[begin:end]:
        cleaned = clean_line(raw)
        if not cleaned or heading_of(cleaned) or is_caption(cleaned):
            continue
        if cleaned.count("|") >= 2:  # table row, not prose
            continue
        if len(cleaned) < min_chars:
            continue
        body.append(cleaned)
    return body


def section_window(
    text: str, number: str, *, after: int | None = None
) -> tuple[int | None, int | None]:
    """Line window ``(start, stop)`` of section ``number`` inside ``text``.

    ``start`` is the first heading that belongs to the section (its number or a
    descendant); it stays ``None`` when the chunk continues a body without
    repeating the heading. ``stop`` is the first later heading that opens a
    *different* section, so a sibling chunk never leaks the next section's
    paragraphs. Pass ``after`` when the matched heading is already known.
    """
    anchor = tuple(int(part) for part in number.split("-"))
    start = after
    for heading in headings(text):
        if start is not None and heading.line <= start:
            continue
        belongs = heading.number == number or (
            heading.depth > len(anchor) and heading.parts[: len(anchor)] == anchor
        )
        if start is None:
            if belongs:
                start = heading.line
                continue
            return start, heading.line
        if not belongs:
            return start, heading.line
    return start, None


def match_heading(query: str, text: str) -> tuple[Heading, float] | None:
    """Return the heading that the *question is asking about*, if any.

    A question matches a heading only when it covers nearly all of the title
    and the title covers nearly all of the question's words. That keeps
    "تنفيذ مرحلة التعرف على الوجه" attached to section 3-5 while leaving a
    normal question such as "كيف يتم التعرف على الوجه؟" to the regular ranker.
    """
    question_terms = set(content_terms(query))
    if not question_terms:
        return None
    numbers = query_numbers(query)
    best: tuple[Heading, float] | None = None
    for heading in headings(text):
        if heading.number in numbers:
            return heading, 1.0
        overlap = question_terms & heading.terms
        if not overlap:
            continue
        title_covered = len(overlap) / len(heading.terms)
        question_covered = len(overlap) / len(question_terms)
        if title_covered < 0.75 or question_covered < 0.75:
            continue
        if len(heading.terms) > 1 and len(overlap) < 2:
            continue
        score = (title_covered + question_covered) / 2
        if best is None or score > best[1]:
            best = (heading, score)
    return best


def starts_with_heading(text: str) -> Heading | None:
    """First non-empty line of a chunk, if it is a heading."""
    for raw in text.splitlines():
        cleaned = clean_line(raw)
        if not cleaned:
            continue
        return heading_of(cleaned)
    return None
