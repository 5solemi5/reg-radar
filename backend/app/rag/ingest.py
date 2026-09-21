"""RAG 수집 파이프라인 (기획서 §7-2).

    Loader → Metadata Normalization → Splitter → Embedding → Vector Store

수집 대상은 법제처의 법령해석례·행정규칙·판례다. 정부 사이트를 스크래핑하는
대신 이쪽을 쓰는 이유는 출처·기관·일자가 이미 구조화되어 있어 FR-013의
metadata 요건을 만족하고, 원문 링크로 사용자가 직접 확인할 수 있기 때문이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.adapters.law.client import LawApiClient
from app.core.config import Settings, get_settings
from app.rag.chunking import chunk_document
from app.rag.embeddings import Embedder, EmbeddingUnavailableError, OpenAIEmbedder
from app.rag.loaders import LawPortalLoader
from app.rag.models import RagChunk, RagDocument
from app.rag.store import VectorStore, build_store

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    """무엇을 얼마나 넣었는지. 인덱스 상태를 사람이 확인할 수 있어야 한다."""

    queries: list[str] = field(default_factory=list)
    documents: int = 0
    chunks: int = 0
    indexed: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"문서 {self.documents}건 → 청크 {self.chunks}개 → 색인 {self.indexed}개"
            + (f" · 건너뜀 {len(self.skipped)}건" if self.skipped else "")
            + (f" · 오류 {len(self.errors)}건" if self.errors else "")
        )


class RagIngestor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
    ):
        self.settings = settings or get_settings()
        self._embedder = embedder
        self._store = store

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OpenAIEmbedder(self.settings)
        return self._embedder

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = build_store(self.settings)
        return self._store

    async def collect(self, queries: list[str]) -> list[RagDocument]:
        documents: list[RagDocument] = []
        seen: set[str] = set()
        async with LawApiClient(settings=self.settings) as client:
            loader = LawPortalLoader(client)
            for query in queries:
                found = await loader.load_all(query)
                for document in found:
                    if document.doc_id not in seen:
                        seen.add(document.doc_id)
                        documents.append(document)
                logger.info("'%s' → 문서 %d건 (누적 %d)", query, len(found), len(documents))
        return documents

    async def index(self, documents: list[RagDocument]) -> IngestReport:
        report = IngestReport(documents=len(documents))

        chunks: list[RagChunk] = []
        for document in documents:
            produced = chunk_document(document)
            if not produced:
                report.skipped.append(f"{document.doc_id}: 청크 없음")
                continue
            chunks.extend(produced)
        report.chunks = len(chunks)

        if not chunks:
            return report

        try:
            vectors = await self.embedder.embed([c.text for c in chunks])
        except EmbeddingUnavailableError as exc:
            report.errors.append(str(exc))
            return report

        report.indexed = await self.store.upsert(chunks, vectors)
        return report

    async def run(self, queries: list[str]) -> IngestReport:
        documents = await self.collect(queries)
        report = await self.index(documents)
        report.queries = queries
        return report
