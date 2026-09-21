"""법제처 OPEN API 응답의 정규화 모델.

AP-07 / BR-006: 분석 시점의 법령 상태를 snapshot으로 보존해 과거 결과를 재현한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.context import LegalContext


class LawSummary(BaseModel):
    """lawSearch.do 목록 1건."""

    model_config = ConfigDict(frozen=True)

    law_id: str = Field(..., description="법령ID")
    mst: str | None = Field(None, description="법령일련번호(MST). 본문 조회 키")
    law_name: str
    law_type: str | None = Field(None, description="법령구분명. 예: 법률, 대통령령")
    ministry: str | None = None
    promulgation_date: date | None = None
    promulgation_no: str | None = None
    effective_date: date | None = None
    revision_type: str | None = Field(None, description="제개정구분명. 예: 일부개정")
    detail_link: str | None = None

    @property
    def fetch_key(self) -> tuple[str, str]:
        """본문 조회 시 사용할 (파라미터명, 값). MST 우선."""
        return ("MST", self.mst) if self.mst else ("ID", self.law_id)


class LawArticle(BaseModel):
    """조문 1건. original_text가 인용 검증(FR-021)의 기준 문자열이다."""

    model_config = ConfigDict(frozen=True)

    article_no: str = Field(..., description="표시용 조문번호. 예: 제15조의2")
    article_key: str | None = Field(None, description="법제처 조문키")
    article_title: str | None = None
    chapter: str | None = Field(
        None, description="소속 편/장/절 제목. 법제처 <조문여부>전문</조문여부> 단위에서 수집."
    )
    effective_date: date | None = Field(None, description="조문 시행일자")
    original_text: str = Field(..., description="조문 원문 전체 (항·호 포함)")
    is_supplementary: bool = Field(False, description="부칙 여부")


class LawSnapshot(BaseModel):
    """분석 시점에 확보한 법령 1건의 공식 상태 (law_snapshots 테이블 대응)."""

    law_id: str
    mst: str | None = None
    law_name: str
    law_type: str | None = None
    ministry: str | None = None
    promulgation_date: date | None = None
    effective_date: date | None = None
    revision_type: str | None = None
    source_url: str | None = None
    articles: list[LawArticle] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = Field("law.go.kr", description="ER-001 대응: 원천이 API인지 cache인지 표시")

    def find_article(self, article_no: str) -> LawArticle | None:
        return next((a for a in self.articles if a.article_no == article_no), None)

    def to_legal_context(self, article_no: str) -> LegalContext:
        """조문 1건을 AI Core 입력용 LegalContext로 변환한다.

        여기서 만들어진 값만이 '법적 사실'로 취급되며, LLM은 이를 수정할 수 없다.
        """
        article = self.find_article(article_no)
        if article is None:
            raise KeyError(f"{self.law_name}에 조문 {article_no}이(가) 없습니다.")
        return LegalContext(
            law_id=self.law_id,
            law_name=self.law_name,
            article_no=article.article_no,
            article_title=article.article_title,
            effective_date=article.effective_date or self.effective_date,
            promulgation_date=self.promulgation_date,
            ministry=self.ministry,
            original_text=article.original_text,
            source_url=self.source_url,
        )
