"""API-based embeddings: supported model, dimensions, prefixes and retries."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, embeddings
from app.main import app

DIM = 384


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def vector(value: float = 1.0) -> list[float]:
    return [value] + [0.0] * (DIM - 1)


@pytest.fixture
def embedder():
    return embeddings.HFInferenceEmbedder(
        model=config.DEFAULT_EMBEDDING_MODEL, api_key="test-key", timeout=1
    )


@pytest.fixture
def e5_embedder():
    return embeddings.HFInferenceEmbedder(
        model="intfloat/multilingual-e5-large", api_key="test-key", timeout=1
    )


def test_default_model_is_supported_and_arabic() -> None:
    # The Hub's inference_provider=hf-inference list is authoritative. E5-small
    # was on this list's predecessor but is no longer served; granite is.
    assert config.DEFAULT_EMBEDDING_MODEL in config.HF_INFERENCE_MODELS
    assert config.MODEL_DIMENSIONS[config.DEFAULT_EMBEDDING_MODEL] == DIM


def test_dimension_follows_the_model_from_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "hf-api")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)
    assert config._embedding_dimension() == 1024

    monkeypatch.setenv("EMBEDDING_MODEL", config.DEFAULT_EMBEDDING_MODEL)
    assert config._embedding_dimension() == DIM

    monkeypatch.setenv("EMBEDDING_DIMENSION", "512")
    assert config._embedding_dimension() == 512


def test_documents_are_normalised_and_use_current_router(monkeypatch, embedder) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, [vector(3.0)])

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    result = embedder.embed(["annual leave policy"])

    assert result.shape == (1, DIM)
    assert np.isclose(float(np.linalg.norm(result[0])), 1.0)
    # The model must come before the pipeline segment (official InferenceClient
    # route). Reversing them gives a misleading "model not supported" 400.
    assert calls[0][0] == (
        "https://router.huggingface.co/hf-inference/models/"
        f"{config.DEFAULT_EMBEDDING_MODEL}/pipeline/feature-extraction"
    )
    # Granite is trained without asymmetric prefixes.
    assert calls[0][1]["json"]["inputs"] == ["annual leave policy"]
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"


def test_e5_models_still_get_asymmetric_prefixes(monkeypatch, e5_embedder) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(200, [[1.0] + [0.0] * 1023])

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    e5_embedder.embed(["annual leave policy"])
    e5_embedder.embed_one("كم يوم إجازة؟")

    assert calls[0]["json"]["inputs"] == ["passage: annual leave policy"]
    assert calls[1]["json"]["inputs"] == ["query: كم يوم إجازة؟"]


def test_rate_limit_is_retried_with_retry_after(monkeypatch, embedder) -> None:
    sleeps = []
    responses = [
        FakeResponse(429, {"error": "rate limit"}, {"Retry-After": "0"}),
        FakeResponse(200, [vector()]),
    ]

    def fake_post(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = embedder.embed_one("sick leave")

    assert result.shape == (DIM,)
    assert sleeps == [0.0]


def test_unexpected_dimension_is_rejected(monkeypatch, embedder) -> None:
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, **kwargs: FakeResponse(200, [[1.0, 0.0, 0.0]]),
    )

    with pytest.raises(ValueError, match="dimension"):
        embedder.embed_one("annual leave")


def test_persistent_failure_is_reported(monkeypatch, embedder) -> None:
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, **kwargs: FakeResponse(503, {"error": "loading"}, {"Retry-After": "0"}),
    )
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="503"):
        embedder.embed_one("annual leave")


def test_hashing_ignores_stale_two_service_settings(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("EMBEDDING_MODEL", config.DEFAULT_EMBEDDING_MODEL)
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")

    # An explicit dimension override still wins, but the advertised model and
    # the default (no override) width ignore the retired remote deployment.
    assert config._embedding_model() == config.HASHING_MODEL
    assert config._embedding_dimension() == 768

    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)
    assert config._embedding_dimension() == config.HASHING_DIMENSION


def test_missing_api_key_falls_back_to_hashing(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "settings",
        replace(config.settings, embedding_backend="hf-api", hf_api_key=""),
    )
    monkeypatch.setattr(embeddings, "_embedder", None)

    embedder = embeddings.get_embedder()

    assert isinstance(embedder, embeddings.HashingEmbedder)
    assert embedder.backend == "hashing"


def test_api_key_selects_the_api_embedder(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "settings",
        replace(
            config.settings,
            embedding_backend="hf-api",
            hf_api_key="abc",
            embedding_model=config.DEFAULT_EMBEDDING_MODEL,
        ),
    )
    monkeypatch.setattr(embeddings, "_embedder", None)

    embedder = embeddings.get_embedder()

    assert isinstance(embedder, embeddings.HFInferenceEmbedder)
    assert embedder.model == config.DEFAULT_EMBEDDING_MODEL


def test_unsupported_model_falls_back_to_supported_default(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "settings",
        replace(
            config.settings,
            embedding_backend="hf-api",
            hf_api_key="abc",
            embedding_model="intfloat/multilingual-e5-small",
        ),
    )
    monkeypatch.setattr(embeddings, "_embedder", None)

    embedder = embeddings.get_embedder()

    assert isinstance(embedder, embeddings.HFInferenceEmbedder)
    assert embedder.model == config.DEFAULT_EMBEDDING_MODEL


def test_health_reports_key_presence_without_the_secret() -> None:
    with TestClient(app) as client:
        check = client.get("/api/v1/health").json()["checks"]["embedding_model"]

    assert isinstance(check["hf_api_key_configured"], bool)


# --------------------------------------------------------------------------- #
# Gemini free-tier embeddings (spec 006)
# --------------------------------------------------------------------------- #
GEMINI_DIM = 768
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def gemini_vector(value: float = 1.0) -> list[float]:
    return [value] + [0.0] * (GEMINI_DIM - 1)


@pytest.fixture
def gemini_embedder():
    return embeddings.GeminiEmbedder(
        model=config.GEMINI_EMBEDDING_MODEL, api_key="gemini-test-key", timeout=1
    )


def test_gemini_model_defaults_to_free_tier_dimension(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_BACKEND", "gemini")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)

    assert config._embedding_model() == config.GEMINI_EMBEDDING_MODEL
    assert config._embedding_dimension() == GEMINI_DIM
    assert config.MODEL_DIMENSIONS[config.GEMINI_EMBEDDING_MODEL] == GEMINI_DIM


def test_documents_use_batch_endpoint_document_task_and_key_header(
    monkeypatch, gemini_embedder
) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, {"embeddings": [{"values": gemini_vector(3.0)}]})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    result = gemini_embedder.embed(["annual leave policy"])

    assert result.shape == (1, GEMINI_DIM)
    assert np.isclose(float(np.linalg.norm(result[0])), 1.0)
    assert calls[0][0] == (
        f"{GEMINI_URL}/{config.GEMINI_EMBEDDING_MODEL}:batchEmbedContents"
    )
    assert calls[0][1]["headers"]["x-goog-api-key"] == "gemini-test-key"
    request = calls[0][1]["json"]["requests"][0]
    assert request["model"] == f"models/{config.GEMINI_EMBEDDING_MODEL}"
    assert request["taskType"] == "RETRIEVAL_DOCUMENT"
    assert request["content"]["parts"][0]["text"] == "annual leave policy"
    assert request["output_dimensionality"] == GEMINI_DIM


def test_query_uses_embed_content_and_query_task(monkeypatch, gemini_embedder) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, {"embedding": {"values": gemini_vector()}})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)

    result = gemini_embedder.embed_one("كم يوم إجازة؟")

    assert result.shape == (GEMINI_DIM,)
    assert calls[0][0] == f"{GEMINI_URL}/{config.GEMINI_EMBEDDING_MODEL}:embedContent"
    payload = calls[0][1]["json"]
    assert "requests" not in payload
    assert payload["taskType"] == "RETRIEVAL_QUERY"
    assert payload["content"]["parts"][0]["text"] == "كم يوم إجازة؟"
    assert payload["output_dimensionality"] == GEMINI_DIM


def test_gemini_rate_limit_is_retried_with_retry_after(
    monkeypatch, gemini_embedder
) -> None:
    sleeps = []
    responses = [
        FakeResponse(
            429,
            {"error": {"message": "quota"}},
            {"Retry-After": "0"},
        ),
        FakeResponse(200, {"embedding": {"values": gemini_vector()}}),
    ]

    def fake_post(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = gemini_embedder.embed_one("sick leave")

    assert result.shape == (GEMINI_DIM,)
    assert sleeps == [0.0]


def test_gemini_unexpected_dimension_is_rejected(monkeypatch, gemini_embedder) -> None:
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, **kwargs: FakeResponse(
            200, {"embedding": {"values": [1.0, 0.0, 0.0]}}
        ),
    )

    with pytest.raises(ValueError, match="dimension"):
        gemini_embedder.embed_one("annual leave")


def test_gemini_error_does_not_echo_api_key(monkeypatch, gemini_embedder) -> None:
    monkeypatch.setattr(
        embeddings.httpx,
        "post",
        lambda url, **kwargs: FakeResponse(
            400, {"error": {"message": "invalid key gemini-test-key"}}
        ),
    )

    with pytest.raises(RuntimeError) as exc:
        gemini_embedder.embed_one("annual leave")

    assert "gemini-test-key" not in str(exc.value)


def test_missing_gemini_key_falls_back_to_hashing(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "settings",
        replace(config.settings, embedding_backend="gemini", gemini_api_key=""),
    )
    monkeypatch.setattr(embeddings, "_embedder", None)

    embedder = embeddings.get_embedder()

    assert isinstance(embedder, embeddings.HashingEmbedder)
    assert embedder.backend == "hashing"


def test_gemini_key_selects_gemini_embedder(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "settings",
        replace(
            config.settings,
            embedding_backend="gemini",
            gemini_api_key="abc",
            embedding_model=config.GEMINI_EMBEDDING_MODEL,
            embedding_dimension=GEMINI_DIM,
        ),
    )
    monkeypatch.setattr(embeddings, "_embedder", None)

    embedder = embeddings.get_embedder()

    assert isinstance(embedder, embeddings.GeminiEmbedder)
    assert embedder.model == config.GEMINI_EMBEDDING_MODEL
    assert embedder.dimension == GEMINI_DIM


def test_old_hf_model_falls_back_to_gemini_default(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings,
        "settings",
        replace(
            config.settings,
            embedding_backend="gemini",
            gemini_api_key="abc",
            embedding_model=config.DEFAULT_EMBEDDING_MODEL,
            embedding_dimension=384,
        ),
    )
    monkeypatch.setattr(embeddings, "_embedder", None)

    embedder = embeddings.get_embedder()

    assert isinstance(embedder, embeddings.GeminiEmbedder)
    assert embedder.model == config.GEMINI_EMBEDDING_MODEL
    assert embedder.dimension == GEMINI_DIM


def test_health_reports_gemini_key_presence_without_the_secret() -> None:
    with TestClient(app) as client:
        check = client.get("/api/v1/health").json()["checks"]["embedding_model"]

    assert isinstance(check["gemini_api_key_configured"], bool)
