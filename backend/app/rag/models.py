"""RAG 문서 모델 (FR-013).

**이 계층의 문서는 법적 근거가 아니다** (BR-004). 법령 원문은 법제처 조문 API가
공급하고, 여기 있는 것은 그 조문을 '실무에서 어떻게 적용하는가'를 보여주는
참고 맥락이다. 둘을 섞지 않기 위해 타입부터 분리한다.

FR-013은 모든 문서가 source, agency, published_at, doc_type, vector_id를 갖도록
요구한다. 출처를 모르는 참고자료는 사용자에게 보여줄 수 없기 때문이다.
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.context import RagContext
from app.domain.enums import DocType


class RagDocument(BaseModel):
    """수집된 원본 문서 1건. 아직 잘리지 않은 상태."""

    model_config = ConfigDict(frozen=True)

    doc_id: str = Field(..., description="출처 시스템의 고유 ID (예: 법제처 일련번호)")
    title: str
    body: str
    doc_type: DocType
    source: str = Field(..., description="원문을 볼 수 있는 URL")
    agency: str | None = Field(None, description="발행/회신 기관")
    published_at: date | None = None
    # 어떤 법령과 관련된 문서인지. Retriever의 metadata filter에 쓰인다.
    related_law_names: list[str] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        """출처를 모르거나 본문이 없는 문서는 인덱싱하지 않는다."""
        return bool(self.body.strip()) and bool(self.source)


class RagChunk(BaseModel):
    """임베딩 단위. 문서 metadata를 그대로 물려받는다."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    doc_id: str
    title: str
    text: str
    doc_type: DocType
    source: str
    agency: str | None = None
    published_at: date | None = None
    related_law_names: list[str] = Field(default_factory=list)
    position: int = Field(0, description="문서 내 순번")

    @classmethod
    def build(cls, document: RagDocument, text: str, position: int) -> RagChunk:
        # 같은 내용을 다시 인덱싱해도 같은 id가 나오도록 내용 해시를 쓴다.
        digest = hashlib.sha1(
            f"{document.doc_id}:{position}:{text}".encode()
        ).hexdigest()[:16]
        return cls(
            chunk_id=f"{document.doc_id}-{position}-{digest}",
            doc_id=document.doc_id,
            title=document.title,
            text=text,
            doc_type=document.doc_type,
            source=document.source,
            agency=document.agency,
            published_at=document.published_at,
            related_law_names=document.related_law_names,
            position=position,
        )

    def to_metadata(self) -> dict:
        """Chroma metadata. 스칼라만 허용되므로 리스트는 구분자로 잇는다."""
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type.value,
            "source": self.source,
            "agency": self.agency or "",
            "published_at": self.published_at.isoformat() if self.published_at else "",
            "related_law_names": "|".join(self.related_law_names),
            "position": self.position,
        }


class RetrievedChunk(BaseModel):
    """검색 결과. score는 유사도(1에 가까울수록 관련)."""

    model_config = ConfigDict(frozen=True)

    chunk: RagChunk
    score: float

    def to_rag_context(self) -> RagContext:
        """AI Core 입력으로 변환한다.

        RagContext는 ContextPacket.rag에 들어가며, 프롬프트에서 항상
        '참고자료(법적 근거 아님)'로 라벨링된다.
        """
        return RagContext(
            doc_id=self.chunk.doc_id,
            source=self.chunk.source,
            agency=self.chunk.agency,
            published_at=self.chunk.published_at,
            doc_type=self.chunk.doc_type,
            title=self.chunk.title,
            snippet=self.chunk.text,
            score=self.score,
        )


def metadata_to_chunk(metadata: dict, text: str) -> RagChunk:
    """Chroma metadata에서 RagChunk를 복원한다."""
    published = metadata.get("published_at") or ""
    related = metadata.get("related_law_names") or ""
    return RagChunk(
        chunk_id=metadata.get("chunk_id", ""),
        doc_id=metadata["doc_id"],
        title=metadata.get("title", ""),
        text=text,
        doc_type=DocType(metadata["doc_type"]),
        source=metadata["source"],
        agency=metadata.get("agency") or None,
        published_at=date.fromisoformat(published) if published else None,
        related_law_names=[x for x in related.split("|") if x],
        position=int(metadata.get("position", 0)),
    )
