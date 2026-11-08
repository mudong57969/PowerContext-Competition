"""Embedding providers.

- ``local``: fastembed + BAAI/bge-small-zh-v1.5 (offline, no API key; real model)
- ``openai``: any OpenAI-compatible /v1/embeddings endpoint
- ``none``: semantic search disabled (retrieval degrades to fulltext, clearly flagged)
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import Settings

log = logging.getLogger("exampilot.embeddings")


class EmbeddingUnavailableError(RuntimeError):
    pass


class EmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.embedding_provider in ("local", "openai")

    @property
    def dimension(self) -> int:
        return self.settings.embedding_dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        provider = self.settings.embedding_provider
        if provider == "none":
            raise EmbeddingUnavailableError("embedding provider is 'none'")
        if provider == "local":
            return self._embed_local(texts)
        if provider == "openai":
            return self._embed_openai(texts)
        raise EmbeddingUnavailableError(f"unknown embedding provider: {provider}")

    # --- local (fastembed) -------------------------------------------------
    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingUnavailableError(
                "fastembed is not installed; install the backend dependencies"
            ) from exc
        with self._lock:
            if self._model is None:
                log.info(
                    "loading local embedding model %s", self.settings.embedding_model
                )
                self._model = TextEmbedding(model_name=self.settings.embedding_model)
        vectors = list(self._model.embed(texts))
        return [v.tolist() for v in vectors]

    # --- OpenAI-compatible --------------------------------------------------
    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        import httpx

        if not self.settings.openai_api_key:
            raise EmbeddingUnavailableError(
                "embedding provider is 'openai' but no API key is configured"
            )
        url = (
            self.settings.openai_base_url.rstrip("/") or "https://api.openai.com/v1"
        ) + "/embeddings"
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        resp = httpx.post(
            url,
            headers=headers,
            json={"model": self.settings.embedding_openai_model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda item: item["index"])
        return [item["embedding"] for item in data]
