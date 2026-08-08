from __future__ import annotations

from math import isfinite

from langchain_openai import OpenAIEmbeddings

from lexora_ai.config import Settings


class OpenAIEmbeddingGateway:
    def __init__(self, settings: Settings) -> None:
        api_key = settings.embedding_api_key or settings.openai_api_key
        if api_key is None:
            raise ValueError("an embedding API key is required")
        options: dict[str, object] = {
            "model": settings.embedding_model,
            "api_key": api_key,
            "check_embedding_ctx_length": False,
            "chunk_size": 64,
        }
        base_url = settings.embedding_base_url or settings.openai_base_url
        if base_url:
            options["base_url"] = base_url
        self._model_name = settings.embedding_model
        self._client = OpenAIEmbeddings(**options)

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        return self._validate(await self._client.aembed_documents(texts), expected=len(texts))

    async def embed_query(self, text: str) -> tuple[float, ...]:
        vectors = self._validate([await self._client.aembed_query(text)], expected=1)
        return vectors[0]

    @staticmethod
    def _validate(vectors: list[list[float]], *, expected: int) -> list[tuple[float, ...]]:
        if len(vectors) != expected:
            raise RuntimeError("embedding provider returned an unexpected vector count")
        dimensions = {len(vector) for vector in vectors}
        if not dimensions or 0 in dimensions or len(dimensions) != 1:
            raise RuntimeError("embedding provider returned inconsistent vector dimensions")
        if any(not isfinite(value) for vector in vectors for value in vector):
            raise RuntimeError("embedding provider returned a non-finite value")
        return [tuple(vector) for vector in vectors]
