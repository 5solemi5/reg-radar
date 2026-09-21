"""Retriever (기획서 §7-2, FR-013).

**검색 결과가 없는 것은 정상이다** (BR-005). 빈 목록을 돌려주면 Context Builder가
'참고자료 없음'을 프롬프트에 명시하고, Validator가 모델이 없는 출처를 지어내는
것을 막는다. 여기서 억지로 무언가를 채우면 그 방어가 무력해진다.
"""

from __future__ import annotations

import logging

from app.domain.context import LegalContext, RagContext, UserContext
from app.rag.embeddings import Embedder, EmbeddingUnavailableError
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)

# 유사도가 이보다 낮으면 관련 없는 문서로 본다. 관련 없는 참고자료는
# 없느니만 못하다 — 사용자가 근거로 오해할 수 있다.
MIN_SCORE = 0.25


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore, *, top_k: int = 5):
        self._embedder = embedder
        self._store = store
        self._top_k = top_k

    @staticmethod
    def build_query(law: LegalContext, user: UserContext) -> str:
        """검색 질의를 만든다.

        조문 원문 전체가 아니라 '법령명 + 조문제목 + 사용자 맥락 + 원문 앞부분'을
        쓴다. 원문을 통째로 넣으면 조문의 형식적 문구가 유사도를 지배해서,
        정작 실무 맥락을 담은 해석례가 밀린다.
        """
        parts = [
            law.law_name,
            law.article_title or "",
            f"{user.industry} {user.job}",
            law.original_text[:300],
        ]
        return " ".join(p for p in parts if p).strip()

    async def retrieve(
        self, law: LegalContext, user: UserContext
    ) -> list[RagContext]:
        query = self.build_query(law, user)
        try:
            vector = await self._embedder.embed_query(query)
        except EmbeddingUnavailableError as exc:
            # 참고자료는 없어도 분석이 성립한다. 실패를 분석 실패로 키우지 않는다.
            logger.info("질의 임베딩 실패 — 참고자료 없이 진행: %s", exc)
            return []

        try:
            results = await self._store.search(
                vector,
                # 문서 단위로 중복을 제거하므로 청크는 넉넉히 받는다.
                top_k=self._top_k * 3,
                # 해당 법령(및 시행령 등 파생 법령)을 다루는 문서로 좁힌다.
                law_names=[law.law_name],
            )
        except Exception as exc:
            logger.warning("참고자료 검색 실패 — 없이 진행: %s", exc)
            return []

        relevant = [r for r in results if r.score >= MIN_SCORE]
        if results and not relevant:
            logger.info(
                "참고자료 %d건을 찾았으나 유사도가 낮아 제외 (최고 %.3f)",
                len(results), results[0].score,
            )

        # 같은 문서의 여러 청크가 상위를 독점하면 참고자료가 한 건짜리가 된다.
        # 문서당 가장 관련 높은 청크 하나만 남겨 다양성을 확보한다.
        seen: set[str] = set()
        deduped: list[RagContext] = []
        for result in relevant:
            if result.chunk.doc_id in seen:
                continue
            seen.add(result.chunk.doc_id)
            deduped.append(result.to_rag_context())
        return deduped[: self._top_k]


class NullRetriever:
    """RAG 미구성 환경용. 항상 빈 목록 — BR-005에 따라 정상 상태다."""

    async def retrieve(self, law: LegalContext, user: UserContext) -> list[RagContext]:
        return []
