"""Embedding backends.

Default: deterministic hashing embedder (instant, no downloads, multilingual
tokenization). BM25 carries lexical retrieval and the LLM decides how to answer
from the retrieved chunks, so the hosted deployment needs no model download or
second service. Optional: sentence-transformers, Hugging Face Inference API
(EMBEDDING_BACKEND=hf-api) and free-tier Gemini (EMBEDDING_BACKEND=gemini).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
from typing import Sequence

import httpx
import numpy as np

from .config import (
    DEFAULT_EMBEDDING_MODEL,
    GEMINI_EMBEDDING_DIMENSION,
    GEMINI_EMBEDDING_MODEL,
    GEMINI_EMBEDDING_MODELS,
    HF_INFERENCE_MODELS,
    MODEL_DIMENSIONS,
    PASSAGE_PREFIXES,
    QUERY_PREFIXES,
    settings,
)

logger = logging.getLogger(__name__)

# Decimals ("0.32", "1.5") are single facts, not two numbers: keep them whole.
_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)+|[^\W_]+", re.UNICODE)
# Arabic diacritics (tashkeel), tatweel and Quranic marks carry no retrieval signal.
_ARABIC_MARKS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")

# Function words carry no topic signal: matching them is what makes a search
# engine answer "CEO salary" with a paragraph about a solenoid.
_EN_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "could", "did", "do", "does", "for", "from", "get", "gets", "had", "has",
    "have", "how", "i", "if", "in", "into", "is", "it", "its", "many", "me",
    "much", "my", "of", "on", "or", "our", "please", "should", "so", "tell",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "to", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
}
_AR_STOPWORDS = {
    "الى", "إلى", "الا", "إلا", "التي", "الذي", "الذين", "الان", "الآن",
    "اي", "أي", "ايضا", "أيضا", "ان", "أن", "انه", "أنه", "انها", "أنها",
    "او", "أو", "اول", "أول", "اين", "أين", "ب", "به", "بها", "بين", "بل",
    "ثم", "حتى", "حيث", "خلال", "دون", "على", "عليه", "عليها", "عن", "عند",
    "عندما", "غير", "ف", "فان", "فإن", "في", "فيه", "فيها", "قد", "كان",
    "كانت", "كل", "كما", "كي", "كيف", "لا", "لدى", "لم", "لن", "له", "لها",
    "لهم", "ما", "ماذا", "متى", "مما", "من", "منذ", "منه", "منها", "نحن",
    "هذه", "هذا", "هم", "هما", "هن", "هو", "هي", "و", "هناك", "هنا", "هل",
    "وفي", "وقد", "ولا", "ومن", "وهو", "وهي", "يا", "يكون", "يمكن",
    "ايها", "أيها", "اللذين", "اللتين", "بعد", "قبل", "حول", "ضمن", "نحو",
    "ضد", "سوف", "اذا", "إذا", "لما", "فيما", "عما", "لكي", "حين", "بينما",
    "كم", "وما", "وماذا", "وذلك", "وكان", "وكانت", "فيه", "فيها", "منهم",
    "لكن", "لكنه", "أما", "اما", "إذ", "اذ", "أيضا", "كذلك", "مثل", "مثلا",
}
_STOPWORDS: set[str] = set()

# Arabic attaches the article and common prepositions to the noun; English adds
# plurals. Removing these keeps "العمل" matching "عمل" and "days" matching "day".
# Single-letter prefixes (و/ف/ب/ك/ل) are deliberately not stripped: they are also
# the first radical of plenty of roots ("وجه", "بصمة", "وقت"), so stripping them
# would merge unrelated words.
_AR_PREFIXES = ("وال", "بال", "كال", "فال", "ولل", "لل", "ال", "وب", "وك", "ول")
# "إطاراً" and "مدة" have to meet "إطار" and "مدة" in the document, so the
# accusative alef, the feminine ta and the possessive/plural endings go too.
_AR_SUFFIXES = (
    "ها", "هم", "هما", "هن", "كم", "كن", "نا", "ات", "ون", "ين", "ان",
    "يه", "ه", "ا", "ي",
)


def _stem(token: str) -> str:
    if token.isascii():
        if len(token) > 4 and token.endswith("ies"):
            return token[:-3] + "y"
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token
    for prefix in _AR_PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 3:
            token = token[len(prefix) :]
            break
    for suffix in _AR_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)]
            break
    return token


def _is_stopword(token: str) -> bool:
    return token in _STOPWORDS


def normalize_text(text: str) -> str:
    """Light Arabic normalisation so vocalised and plain spellings match."""
    text = _ARABIC_MARKS_RE.sub("", text or "")
    return (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
        .replace("ة", "ه")
    )


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text).lower())


_STOPWORDS = _EN_STOPWORDS | {normalize_text(word) for word in _AR_STOPWORDS}


def content_terms(text: str) -> list[str]:
    """Return weighted-worthy terms: no stopwords, lightly stemmed.

    Used for keyword matching, coverage, embeddings and sentence selection.
    Stopwords are checked before *and* after stemming so a clitic form such as
    "وما" that reduces to a stopword does not leak into the index.
    """
    terms: list[str] = []
    for token in tokenize(text):
        if _is_stopword(token):
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        stemmed = _stem(token)
        if not stemmed or _is_stopword(stemmed):
            continue
        terms.append(stemmed)
    return terms


class HashingEmbedder:
    """Hashing trick embedder: fast, offline, deterministic, multilingual.

    Vectors are built from *content* terms, not raw tokens. Hashing every
    occurrence of "من"/"the" would give every chunk in a corpus the same huge
    shared component, collapsing all cosine similarities into one flat band.
    """

    backend = "hashing"
    model = "hashing"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        counts: dict[str, int] = {}
        for token in content_terms(text):
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign * (1.0 + math.log(count))
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.vstack([self.embed_one(t) for t in texts])


class SentenceTransformerEmbedder:
    backend = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer(model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return np.asarray(vectors, dtype=np.float32)


class HFInferenceEmbedder:
    """Hugging Face Inference API embedder (feature-extraction pipeline).

    The model determines the vector width; a deployment variable must not be
    trusted for it. E5 models also need asymmetric query/passage prefixes, which
    are applied here so callers keep the same ``embed`` / ``embed_one`` interface.
    """

    backend = "hf-api"

    _RETRYABLE = {429, 500, 502, 503, 504}
    _MAX_ATTEMPTS = 3

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or settings.hf_api_key
        # The old api-inference.huggingface.co host no longer resolves. The
        # official InferenceClient builds this route as
        #   /hf-inference/models/{model}/pipeline/{task}
        # (see huggingface.js: _t.makeRoute). The model must come BEFORE the
        # pipeline segment; reversing them yields a misleading 400 from the
        # router instead of a 404.
        self.base_url = "https://router.huggingface.co/hf-inference"
        self.timeout = timeout
        self._dim = MODEL_DIMENSIONS.get(model, settings.embedding_dimension)
        self._query_prefix = QUERY_PREFIXES.get(model, "")
        self._passage_prefix = PASSAGE_PREFIXES.get(model, "")

    @property
    def dimension(self) -> int:
        return self._dim

    def _embed(self, texts: Sequence[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)

        inputs = [f"{prefix}{text}" for text in texts] if prefix else list(texts)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/models/{self.model}/pipeline/feature-extraction"
        all_vectors: list[list[float]] = []

        for start in range(0, len(inputs), 16):
            payload = {
                "inputs": inputs[start : start + 16],
                "options": {"wait_for_model": True, "use_cache": True},
                "parameters": {"truncate": True},
            }
            response = None
            for attempt in range(self._MAX_ATTEMPTS):
                response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                if response.status_code not in self._RETRYABLE:
                    break
                if attempt == self._MAX_ATTEMPTS - 1:
                    break
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else 2.0**attempt
                except ValueError:
                    delay = 2.0**attempt
                time.sleep(min(delay, 10.0))

            if response is None:  # pragma: no cover - defensive
                raise RuntimeError("Embedding API returned no response")
            if response.status_code >= 400:
                try:
                    detail = str(response.json())[:200]
                except Exception:  # noqa: BLE001
                    detail = ""
                raise RuntimeError(
                    f"Embedding API returned HTTP {response.status_code}: {detail} "
                    f"(model={self.model}, url={url})"
                )

            data = response.json()
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"Embedding API error: {data['error']}")
            if not isinstance(data, list) or not data:
                raise ValueError("Embedding API returned no vectors")

            vectors = data
            if isinstance(vectors[0][0], list):
                # Multi-vector models (e.g. ColBERT) -> one mean vector per text.
                vectors = [
                    [sum(column) / len(column) for column in zip(*text_vectors)]
                    for text_vectors in vectors
                ]
            all_vectors.extend(vectors)

        matrix = np.asarray(all_vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self._dim:
            actual = matrix.shape[1] if matrix.ndim == 2 else matrix.shape
            raise ValueError(
                f"Embedding dimension changed: model {self.model} returned {actual}, "
                f"expected {self._dim}. Re-index documents with the matching EMBEDDING_MODEL."
            )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-12)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts, self._passage_prefix)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], self._query_prefix)[0]

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed_query(text)


class GeminiEmbedder:
    """Google Gemini Developer API embedder (free tier, text-only).

    ``gemini-embedding-001`` is trained with asymmetric retrieval tasks, so
    documents must be indexed with ``RETRIEVAL_DOCUMENT`` and queries embedded
    with ``RETRIEVAL_QUERY``. The key travels in a header, never in the URL or
    an error message. Non-default widths are normalised manually: the model
    only auto-normalises its native 3072-dimensional output.
    """

    backend = "gemini"

    _RETRYABLE = {429, 500, 502, 503, 504}
    _MAX_ATTEMPTS = 3
    _BATCH_SIZE = 16

    def __init__(
        self,
        model: str = GEMINI_EMBEDDING_MODEL,
        api_key: str | None = None,
        dimension: int | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or settings.gemini_api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.timeout = timeout
        self._dim = dimension or GEMINI_EMBEDDING_MODELS.get(
            model, GEMINI_EMBEDDING_DIMENSION
        )

    @property
    def dimension(self) -> int:
        return self._dim

    def _request(self, text: str, task_type: str) -> dict:
        return {
            "model": f"models/{self.model}",
            "taskType": task_type,
            "output_dimensionality": self._dim,
            "content": {"parts": [{"text": text}]},
        }

    def _post(self, url: str, payload: dict, headers: dict[str, str]) -> dict:
        response = None
        for attempt in range(self._MAX_ATTEMPTS):
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
            if response.status_code not in self._RETRYABLE:
                break
            if attempt == self._MAX_ATTEMPTS - 1:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else 2.0**attempt
            except ValueError:
                delay = 2.0**attempt
            time.sleep(min(delay, 10.0))

        if response is None:  # pragma: no cover - defensive
            raise RuntimeError("Gemini embedding API returned no response")
        if response.status_code >= 400:
            try:
                detail = str(response.json())[:200]
            except Exception:  # noqa: BLE001
                detail = ""
            if self.api_key:
                detail = detail.replace(self.api_key, "[redacted]")
            raise RuntimeError(
                f"Gemini embedding API returned HTTP {response.status_code}: {detail} "
                f"(model={self.model}, url={url})"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("Gemini embedding API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Gemini embedding API returned an unexpected payload")
        return data

    @staticmethod
    def _values(item: object) -> list[float]:
        values = item.get("values") if isinstance(item, dict) else None
        if not values:
            raise ValueError("Gemini embedding API returned an empty vector")
        return values

    def _embed(
        self, texts: Sequence[str], task_type: str, *, batched: bool
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        all_vectors: list[list[float]] = []

        if batched:
            url = f"{self.base_url}/{self.model}:batchEmbedContents"
            for start in range(0, len(texts), self._BATCH_SIZE):
                batch = list(texts[start : start + self._BATCH_SIZE])
                payload = {
                    "requests": [self._request(text, task_type) for text in batch]
                }
                data = self._post(url, payload, headers)
                items = data.get("embeddings")
                if not items:
                    raise ValueError("Gemini embedding API returned no vectors")
                if len(items) != len(batch):
                    raise ValueError(
                        f"Gemini returned {len(items)} vectors for {len(batch)} inputs"
                    )
                all_vectors.extend(self._values(item) for item in items)
        else:
            url = f"{self.base_url}/{self.model}:embedContent"
            data = self._post(url, self._request(texts[0], task_type), headers)
            item = data.get("embedding")
            if not item:
                raise ValueError("Gemini embedding API returned no vectors")
            all_vectors.append(self._values(item))

        matrix = np.asarray(all_vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self._dim:
            actual = matrix.shape[1] if matrix.ndim == 2 else matrix.shape
            raise ValueError(
                f"Embedding dimension changed: model {self.model} returned {actual}, "
                f"expected {self._dim}. Re-index documents with the matching EMBEDDING_MODEL "
                "and EMBEDDING_DIMENSION."
            )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-12)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts, "RETRIEVAL_DOCUMENT", batched=True)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "RETRIEVAL_QUERY", batched=False)[0]

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed_query(text)


_embedder = None
_embedder_lock = threading.Lock()


def get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                backend = settings.embedding_backend
                if backend == "hf-api" and not settings.hf_api_key:
                    logger.warning(
                        "HF_API_KEY is empty; falling back to offline hashing embeddings"
                    )
                    _embedder = HashingEmbedder(settings.embedding_dimension)
                elif backend == "hf-api":
                    model = settings.embedding_model
                    if model not in HF_INFERENCE_MODELS:
                        # Dashboard env vars override render.yaml. An old or
                        # unsupported model would fail every upload with a 400;
                        # use the known-good default instead and say so loudly.
                        logger.warning(
                            "Embedding model %s is not served by hf-inference; "
                            "using %s instead. Set EMBEDDING_MODEL in the dashboard.",
                            model,
                            DEFAULT_EMBEDDING_MODEL,
                        )
                        model = DEFAULT_EMBEDDING_MODEL
                    _embedder = HFInferenceEmbedder(model, settings.hf_api_key)
                elif backend == "gemini":
                    if not settings.gemini_api_key:
                        logger.warning(
                            "GEMINI_API_KEY is empty; falling back to offline hashing embeddings"
                        )
                        _embedder = HashingEmbedder(settings.embedding_dimension)
                    else:
                        model = settings.embedding_model
                        dimension = settings.embedding_dimension
                        if model not in GEMINI_EMBEDDING_MODELS:
                            # Render dashboard values override render.yaml. An old
                            # hf-api model id would be rejected by Google and its
                            # 384 width would corrupt a Gemini vector store.
                            logger.warning(
                                "Embedding model %s is not served by Gemini; using %s "
                                "instead. Set EMBEDDING_MODEL in the dashboard.",
                                model,
                                GEMINI_EMBEDDING_MODEL,
                            )
                            model = GEMINI_EMBEDDING_MODEL
                            dimension = GEMINI_EMBEDDING_DIMENSION
                        _embedder = GeminiEmbedder(
                            model, settings.gemini_api_key, dimension
                        )
                elif backend in {"st", "sentence-transformers", "sentence_transformers"}:
                    try:
                        _embedder = SentenceTransformerEmbedder(settings.embedding_model)
                    except Exception:
                        _embedder = HashingEmbedder(settings.embedding_dimension)
                else:
                    _embedder = HashingEmbedder(settings.embedding_dimension)
            logger.info(
                "Embedding backend selected: backend=%s model=%s dimension=%s",
                getattr(_embedder, "backend", "unknown"),
                getattr(_embedder, "model", "unknown"),
                getattr(_embedder, "dimension", "unknown"),
            )
    return _embedder
