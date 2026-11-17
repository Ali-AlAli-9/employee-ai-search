"""Section-title questions must answer from the section body, not a caption.

A question that repeats a numbered heading used to retrieve the chunk where the
heading falls at the end (often right after a figure caption) and quote that
caption. These tests pin the two guarantees that fixed it: the section body is
retrieved with the anchor, and the synthesizer never uses heading/caption lines.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.ingestion import (
    _is_toc_only_chunk,
    _normalize_pdf_arabic,
    _reverse_visual_order_line,
)
from app.main import app
from app.structure import match_heading, section_lines

client = TestClient(app)
ADMIN = {"X-API-Key": "dev-admin-key"}
USER = {"X-API-Key": "dev-user-key"}

FILLER = (
    "يتكون النظام من وحدة تحكم مركزية ولوحة Arduino Uno وكاميرا ومحرك سيرفو "
    "ووحدة ريليه وقفل كهرومغناطيسي وحساسات متعددة تعمل معاً لتنفيذ دورة العمل "
    "الكاملة داخل الخزنة الذكية."
)

# Long enough to split into two chunks around section 3-5, the way the real
# thesis splits: the heading lands at a chunk boundary and a caption precedes it.
SECTION_DOC = "\n\n".join(
    [
        "3-1 مقدمة الفصل",
        "يقدم هذا الفصل بيئة التنفيذ ومكونات النظام والبنية العامة والتسلسل "
        "التشغيلي والمراحل التفصيلية للتنفيذ والاختبار.",
        "3-2 بيئة التنفيذ ومكونات النظام",
        FILLER,
        FILLER,
        "3-3 البنية العامة للنظام",
        FILLER,
        "3-4 التسلسل التشغيلي العام",
        "يبدأ النظام بالتحقق من المستشعرات ثم يفعّل الكاميرا لالتقاط الصور ثم "
        "يمررها إلى مرحلة التعرف على الوجه قبل السماح بإدخال كلمة المرور.",
        "الشكل (3-4): مخطط التسلسل التشغيلي العام للنظام الذكي.",
        "3-5 تنفيذ مرحلة التعرف على الوجه",
        "3-5-1 تهيئة النموذج والبصمة المرجعية",
        "يتم تحميل البصمة المرجعية للوجه من الملف target_embedding.npy ثم حساب "
        "التشابه باستخدام دالة cosine_similarity مع عتبة قبول THRESHOLD 0.32 "
        "لاتخاذ قرار المطابقة.",
        "3-5-2 تخفيض معدل الاستدلال واتخاذ القرار",
        "يعمل النظام على تحليل كل إطار خامس بمعدل 10 إطارات في الثانية لتقليل "
        "الحمل الحسابي قبل اتخاذ قرار المطابقة النهائي.",
        "3-6 تنفيذ كلمة المرور بالأصابع",
        "يعتمد النظام على مكتبة MediaPipe Hands لعد الأصابع المرفوعة وبناء "
        "تسلسل كلمة المرور.",
    ]
)


@pytest.fixture(scope="module")
def section_document():
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("sections.txt", io.BytesIO(SECTION_DOC.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 202, response.text
    yield response.json()["document_id"]
    client.delete(f"/api/v1/documents/{response.json()['document_id']}", headers=ADMIN)


def test_match_heading_only_for_section_titles():
    text = "3-5 تنفيذ مرحلة التعرف على الوجه\nنص القسم."
    matched = match_heading("تنفيذ مرحلة التعرف على الوجه", text)
    assert matched is not None
    assert matched[0].number == "3-5"

    # A normal question about the same words is not a section request.
    assert match_heading("كيف يتم التعرف على الوجه؟", text) is None

    numbered = match_heading("ماذا يوجد في القسم 3-5؟", text)
    assert numbered is not None and numbered[0].number == "3-5"


def test_section_lines_skip_headings_captions_and_tables():
    text = (
        "3-5 تنفيذ مرحلة التعرف على الوجه\n"
        "3-5-1 تهيئة النموذج والبصمة المرجعية\n"
        "يتم تحميل البصمة المرجعية من الملف target_embedding.npy مع عتبة 0.32.\n"
        "الشكل (3-5): مخطط تدفق مرحلة التعرف على الوجه.\n"
        "العتبة | القيمة | الملاحظة\n"
        "3-5-2 تخفيض معدل الاستدلال واتخاذ القرار\n"
        "يعمل النظام على تحليل كل إطار خامس لتقليل الحمل الحسابي."
    )
    lines = section_lines(text, after=0)
    joined = "\n".join(lines)
    assert "target_embedding" in joined
    assert "كل إطار خامس" in joined
    assert "الشكل" not in joined
    assert "العتبة | القيمة" not in joined
    assert "3-5-2" not in joined


def test_toc_only_chunks_are_rejected():
    toc = "1-5 أهداف المشروع .............. 12\n2-3 الخزنة الذكية ........... 24"
    mixed = toc + "\n3-5 تنفيذ مرحلة التعرف على الوجه ..... 53"
    prose = "يهدف المشروع إلى تصميم خزنة ذكية تعتمد على التعرف على الوجه."
    assert _is_toc_only_chunk(toc) is True
    assert _is_toc_only_chunk(mixed) is True
    assert _is_toc_only_chunk(prose) is False
    assert _is_toc_only_chunk("E = [e1, e2, ... , ed]" + "\n" + prose) is False


def test_visual_order_pdf_text_is_repaired():
    logical = "يتم التعرف على الوجه في النظام الذكي"
    visual = _reverse_visual_order_line(logical)
    assert visual != logical
    assert _normalize_pdf_arabic(visual) == logical
    assert _normalize_pdf_arabic(logical) == logical
    assert _normalize_pdf_arabic("Face similarity threshold 0.32") == (
        "Face similarity threshold 0.32"
    )


def test_section_title_search_returns_the_body(section_document):
    response = client.post(
        "/api/v1/search",
        headers=USER,
        json={"query": "تنفيذ مرحلة التعرف على الوجه", "top_k": 5},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results

    section_hits = [r for r in results if (r.get("section") or {}).get("mode") == "title"]
    assert section_hits, "the section anchor was not detected"
    assert any(r["section"]["number"] == "3-5" for r in section_hits)

    texts = "\n".join(r["text"] for r in results[:4])
    assert "target_embedding" in texts
    assert "إطار خامس" in texts


def test_section_title_answer_skips_caption(section_document):
    response = client.post(
        "/api/v1/chat",
        headers=USER,
        json={
            "message": "تنفيذ مرحلة التعرف على الوجه",
            "stream": False,
            "language": "ar",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "لم أجد معلومات ذات صلة" not in body["answer"]
    assert "الشكل" not in body["answer"]
    assert "0.32" in body["answer"] or "target_embedding" in body["answer"]
    assert body["citations"]
