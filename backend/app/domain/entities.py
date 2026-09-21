"""영속화 엔티티 (기획서 §9 데이터 모델).

AI 입력용 Context(app/domain/context.py)와 구분한다. Profile은 저장되는 것이고
UserContext는 그로부터 파생되어 LLM에 들어가는 것이다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.context import UserContext
from app.domain.enums import AnalysisStatus, Applicability, CompanySize


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


class Profile(BaseModel):
    """profiles 테이블 (FR-002)."""

    user_id: str
    job: str
    industry: str
    company_size: CompanySize
    employee_count: int | None = None
    interests: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def to_user_context(self) -> UserContext:
        return UserContext(
            job=self.job,
            industry=self.industry,
            company_size=self.company_size,
            employee_count=self.employee_count,
            interests=self.interests,
        )


class ResultCounts(BaseModel):
    """대시보드 요약용 집계 (FR-015)."""

    model_config = ConfigDict(frozen=True)

    action: int = 0
    decision: int = 0
    awareness: int = 0
    hold: int = 0
    not_applicable: int = 0
    rejected: int = 0

    @property
    def total(self) -> int:
        return (
            self.action + self.decision + self.awareness
            + self.hold + self.not_applicable + self.rejected
        )


class Analysis(BaseModel):
    """analyses 테이블 (FR-003). 상태 머신은 04 설계서 §10-1을 따른다."""

    analysis_id: str = Field(default_factory=_uuid)
    user_id: str
    status: AnalysisStatus = AnalysisStatus.CREATED
    period_from: date | None = None
    period_to: date | None = None
    law_query: str | None = Field(None, description="법령명 직접 지정 시")
    trace_id: str = Field(default_factory=_uuid)

    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    laws_examined: int = 0
    articles_changed: int = 0
    counts: ResultCounts = Field(default_factory=ResultCounts)
    error: str | None = Field(None, description="FAILED일 때의 사용자용 사유")

    # 관측 (NFR-009). 비용과 성능을 결과 전체를 읽지 않고 볼 수 있게 한다.
    chain_calls: int = 0
    total_tokens: int = 0

    # AP-07/BR-006: 이 분석이 사용한 법령 snapshot을 추적한다.
    snapshot_law_ids: list[str] = Field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.status in (AnalysisStatus.COMPLETED, AnalysisStatus.FAILED)

    @property
    def is_active(self) -> bool:
        return self.status in (AnalysisStatus.CREATED, AnalysisStatus.RUNNING)


class Feedback(BaseModel):
    """feedback 테이블 (FR-019)."""

    feedback_id: str = Field(default_factory=_uuid)
    result_id: str
    user_id: str
    helpful: bool
    correction_type: str | None = Field(
        None, description="wrong_applicability | wrong_grade | wrong_citation | other"
    )
    comment: str | None = None
    created_at: datetime = Field(default_factory=_now)


class SavedRegulation(BaseModel):
    """saved_regulations 테이블 (FR-017)."""

    saved_id: str = Field(default_factory=_uuid)
    user_id: str
    result_id: str
    law_id: str
    law_name: str
    article_no: str
    note: str | None = None
    created_at: datetime = Field(default_factory=_now)


class HoldRevision(BaseModel):
    """보류 재판정 이력 (FR-008, BR-008).

    기존 결과를 덮어쓰지 않고 새 revision을 쌓아 판정 변화를 추적한다.
    """

    revision_id: str = Field(default_factory=_uuid)
    original_result_id: str
    new_result_id: str
    user_id: str
    added_context: dict[str, str] = Field(
        default_factory=dict, description="사용자가 추가로 입력한 정보"
    )
    previous_applicability: Applicability
    new_applicability: Applicability
    created_at: datetime = Field(default_factory=_now)
