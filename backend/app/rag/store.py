"""벡터 저장소 (기획서 §7-2, ADR-008).

로컬은 Chroma, 운영은 Pinecone을 쓸 수 있도록 Protocol로 분리한다.
테스트는 네트워크 없이 도는 인메모리 구현을 쓴다.

FR-013: 검색은 Top-K와 metadata filter를 함께 쓴다. 관련 없는 법령의 해석례가
섞이면 참고자료가 오히려 오해를 만든다.
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Protocol

from app.rag.models import RagChunk, RetrievedChunk, metadata_to_chunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "reg_radar_references"

# 법령명 필터는 벡터 검색 뒤에 적용되므로, 필터를 통과할 후보가 남도록
# 넉넉히 조회한다.
OVERFETCH_MULTIPLIER = 20
MAX_FETCH = 200


class VectorStore(Protocol):
    async def upsert(self, chunks: list[RagChunk], vectors: list[list[float]]) -> int: ...
    async def search(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        law_names: list[str] | None = None,
        doc_types: list[str] | None = None,
    ) -> list[RetrievedChunk]: ...
    async def count(self) -> int: ...


_WS = re.compile(r"\s+")


def normalize_law_name(name: str) -> str:
    """법령명 비교용 정규화.

    같은 법을 문서마다 다르게 띄어 쓴다. 판례 제목은 '개인정보보호법위반'처럼
    붙여 쓰고, 법령 API는 '개인정보 보호법'으로 준다. 공백을 무시해야 둘이
    같은 법으로 인식된다 — 실제로 이 차이 때문에 관련 판례가 전부 걸러졌다.
    """
    return _WS.sub("", name)


def _matches(metadata: dict, law_names: list[str] | None, doc_types: list[str] | None) -> bool:
    """metadata filter (FR-013).

    법령명은 부분 일치를 허용한다. '개인정보 보호법'으로 검색할 때
    '개인정보 보호법 시행령'을 다루는 문서도 실무적으로 관련이 있기 때문이다.
    """
    if doc_types and metadata.get("doc_type") not in doc_types:
        return False
    if law_names:
        haystack = normalize_law_name(
            f"{metadata.get('related_law_names') or ''} {metadata.get('title') or ''}"
        )
        if not any(name and normalize_law_name(name) in haystack for name in law_names):
            return False
    return True


class InMemoryVectorStore:
    """테스트·소규모 실험용. 코사인 유사도를 직접 계산한다."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}
        self._chunks: dict[str, RagChunk] = {}

    async def upsert(self, chunks: list[RagChunk], vectors: list[list[float]]) -> int:
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._vectors[chunk.chunk_id] = vector
            self._chunks[chunk.chunk_id] = chunk
        return len(chunks)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    async def search(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        law_names: list[str] | None = None,
        doc_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        for chunk_id, stored in self._vectors.items():
            chunk = self._chunks[chunk_id]
            if not _matches(chunk.to_metadata(), law_names, doc_types):
                continue
            scored.append(
                RetrievedChunk(chunk=chunk, score=self._cosine(vector, stored))
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    async def count(self) -> int:
        return len(self._vectors)

    def clear(self) -> None:
        self._vectors.clear()
        self._chunks.clear()


class ChromaVectorStore:
    """로컬 영속 저장소. 디렉터리에 인덱스를 보존한다."""

    def __init__(self, persist_dir: str | Path = ".chroma"):
        import chromadb

        path = Path(persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(path))
        # 임베딩은 우리가 직접 만들어 넣는다. Chroma의 기본 임베딩 함수를 쓰면
        # 수집과 검색에서 다른 모델이 쓰일 위험이 있다.
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )

    async def upsert(self, chunks: list[RagChunk], vectors: list[list[float]]) -> int:
        if not chunks:
            return 0
        self._collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[{**c.to_metadata(), "chunk_id": c.chunk_id} for c in chunks],
        )
        return len(chunks)

    async def search(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        law_names: list[str] | None = None,
        doc_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        where = {"doc_type": {"$in": doc_types}} if doc_types else None
        # 법령명은 부분 일치가 필요해 Chroma의 where로 표현할 수 없으므로 넉넉히
        # 받아 파이썬에서 거른다. 배수가 작으면 상위 결과가 전부 필터에서
        # 탈락해 0건이 되는 일이 생긴다 — 실제로 배수 5에서 그런 일이 있었다.
        fetch = min(top_k * OVERFETCH_MULTIPLIER, MAX_FETCH) if law_names else top_k
        result = self._collection.query(
            query_embeddings=[vector],
            n_results=max(fetch, 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        retrieved: list[RetrievedChunk] = []
        for text, metadata, distance in zip(documents, metadatas, distances, strict=False):
            if not _matches(metadata, law_names, doc_types):
                continue
            # cosine distance → 유사도
            retrieved.append(
                RetrievedChunk(
                    chunk=metadata_to_chunk(dict(metadata), text),
                    score=round(1.0 - float(distance), 4),
                )
            )
            if len(retrieved) >= top_k:
                break
        return retrieved

    async def count(self) -> int:
        return self._collection.count()


def build_store(settings) -> VectorStore:
    """설정에 따라 저장소를 고른다."""
    if settings.vector_store == "chroma":
        return ChromaVectorStore(settings.chroma_persist_dir)
    raise NotImplementedError(
        f"지원하지 않는 vector_store: {settings.vector_store}. "
        "Pinecone은 운영 전환 시 구현한다 (ADR-008)."
    )
