"""임베딩 (기획서 §7-2).

배치로 묶어 호출한다. 청크마다 한 번씩 호출하면 수집이 느려지고 비용도 올라간다.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# OpenAI 임베딩 API의 배치 상한을 넉넉히 밑도는 값.
BATCH_SIZE = 64


class EmbeddingUnavailableError(RuntimeError):
    """임베딩을 만들 수 없음. RAG 없이 분석은 계속되어야 한다 (BR-005)."""


class Embedder(Protocol):
    """테스트에서 결정적 구현으로 대체하기 위한 지점."""

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise EmbeddingUnavailableError("OPENAI_API_KEY가 설정되지 않았습니다.")
        from langchain_openai import OpenAIEmbeddings

        self._client = OpenAIEmbeddings(
            model=self.settings.embedding_model,
            api_key=self.settings.openai_api_key,
        )
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int:
        # text-embedding-3-small은 1536. 실제 값은 첫 호출에서 확정된다.
        return self._dimensions or 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                vectors.extend(await self._client.aembed_documents(batch))
            except Exception as exc:
                raise EmbeddingUnavailableError(f"임베딩 실패: {exc}") from exc
        if vectors:
            self._dimensions = len(vectors[0])
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        try:
            return await self._client.aembed_query(text)
        except Exception as exc:
            raise EmbeddingUnavailableError(f"질의 임베딩 실패: {exc}") from exc
