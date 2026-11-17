"""Retrieval quality guarantees: tokenisation, gating and honest abstention."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.embeddings import content_terms
from app.main import app

client = TestClient(app)
ADMIN = {"X-API-Key": "dev-admin-key"}
USER = {"X-API-Key": "dev-user-key"}

FAQS = b"""
Badge threshold. The acceptance THRESHOLD = 0.32 for face similarity.
Each frame is analysed every fifth frame at 10 fps.
The actuator servo turns to 180 degrees when the OPEN command arrives.
Employees receive 20 days of annual leave per year.
"""


@pytest.fixture(scope="module", autouse=True)
def faq_document():
    response = client.post(
        "/api/v1/documents/upload",
        headers=ADMIN,
        files={"file": ("faq.txt", io.BytesIO(FAQS), "text/plain")},
    )
    assert response.status_code == 202, response.text
    yield response.json()["document_id"]
    client.delete(f"/api/v1/documents/{response.json()['document_id']}", headers=ADMIN)


def test_content_terms_strip_stopwords():
    terms = content_terms("What is the threshold for the face similarity?")
    assert "0.32" not in terms
    assert not {"what", "is", "the", "for"} & set(terms)
    assert {"threshold", "face", "similarity"} <= set(terms)


def test_decimal_numbers_survive_tokenisation():
    # A threshold is one fact, not "0" and "32"; keeping it whole gives the
    # number a high IDF weight instead of matching every year in the document.
    assert content_terms("THRESHOLD = 0.32") == ["threshold", "0.32"]


def test_arabic_light_stemming():
    assert content_terms("الإطارات") == content_terms("إطاراً") == ["اطار"]
    assert content_terms("كلمة المرور") == ["كلم", "مرور"]


def test_relevant_question_is_retrieved():
    response = client.post(
        "/api/v1/search", headers=USER, json={"query": "face similarity threshold", "top_k": 5}
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert "0.32" in results[0]["text"]


def test_unrelated_question_returns_no_evidence():
    response = client.post(
        "/api/v1/search", headers=USER, json={"query": "bitcoin price today", "top_k": 5}
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_chat_abstains_instead_of_quoting_unrelated_text():
    response = client.post(
        "/api/v1/chat",
        headers=USER,
        json={"message": "What is the CEO's annual salary?", "stream": False, "language": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "couldn't find relevant information" in body["answer"].lower()
    assert body["citations"] == []
    assert body["confidence"] == 0.0


def test_chat_answers_with_citation_when_evidence_exists():
    response = client.post(
        "/api/v1/chat",
        headers=USER,
        json={"message": "What is the face similarity threshold?", "stream": False, "language": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["citations"]
    assert "0.32" in body["answer"]
