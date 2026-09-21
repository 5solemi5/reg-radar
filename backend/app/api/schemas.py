"""API 요청/응답 스키마 (AP-06).

도메인 모델을 그대로 노출하지 않는다. 프론트가 보는 계약과 내부 모델이 같은
속도로 변해야 할 이유가 없고, AP-05(근거 분리)를 응답 형태로 못 박기 위해서다.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.entities import Analysis, Profile, ResultCounts
from app.domain.enums import (
    ActionGrade,
    AnalysisStatus,
    Applicability,
    ChangeType,
    CompanySize,
    DocType,
    ResultStatus,
)
from app.domain.result import AnalysisResult

# ── 프로필 ────────────────────────────────────────────────────────────


class ProfileIn(BaseModel):
    """FR-002. 필수값이 없으면 스키마 단계에서 거부된다."""

    model_config = ConfigDict(extra="forbid")

    job: str = Field(..., min_length=1, max_length=100)
    industry: str = Field(..., min_length=1, max_length=100)
    company_size: CompanySize
    employee_count: int | None = Field(
        None, ge=0, le=1_000_000,
        description="상시근로자 수. 없으면 규모 조건에서 보류가 날 수 있다.",
    )
    interests: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("job", "industry")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return v.strip()


class ProfilePatch(BaseModel):
    """PATCH — 보낸 필드만 바꾼다."""

    model_config = ConfigDict(extra="forbid")

    job: str | None = Field(None, min_length=1, max_length=100)
    industry: str | None = Field(None, min_length=1, max_length=100)
    company_size: CompanySize | None = None
    employee_count: int | None = Field(None, ge=0, le=1_000_000)
    interests: list[str] | None = Field(None, max_length=20)


class ProfileOut(BaseModel):
    user_id: str
    job: str
    industry: str
    company_size: CompanySize
    employee_count: int | None
    interests: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, profile: Profile) -> ProfileOut:
        return cls(**profile.model_dump())


# ── 분석 ──────────────────────────────────────────────────────────────


class AnalysisCreate(BaseModel):
    """FR-003. 기간 또는 법령명으로 분석 범위를 정한다."""

    model_config = ConfigDict(extra="forbid")

    period_from: date | None = Field(None, description="시행일 기준 시작일")
    period_to: date | None = Field(None, description="시행일 기준 종료일")
    law_query: str | None = Field(
        None, max_length=100, description="특정 법령만 분석할 때의 법령명"
    )
    max_laws: int = Field(3, ge=1, le=10, description="이번 분석에서 다룰 최대 법령 수")

    @field_validator("period_to")
    @classmethod
    def _range_order(cls, v: date | None, info) -> date | None:
        start = info.data.get("period_from")
        if v and start and v < start:
            raise ValueError("period_to는 period_from보다 빠를 수 없습니다.")
        return v


class CountsOut(BaseModel):
    action: int
    decision: int
    awareness: int
    hold: int
    not_applicable: int
    rejected: int
    total: int

    @classmethod
    def of(cls, counts: ResultCounts) -> CountsOut:
        return cls(**counts.model_dump(), total=counts.total)


class AnalysisOut(BaseModel):
    analysis_id: str
    status: AnalysisStatus
    period_from: date | None
    period_to: date | None
    law_query: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    laws_examined: int
    articles_changed: int
    counts: CountsOut
    error: str | None
    trace_id: str

    @classmethod
    def of(cls, analysis: Analysis) -> AnalysisOut:
        data = analysis.model_dump(exclude={"user_id", "counts", "snapshot_law_ids"})
        return cls(**data, counts=CountsOut.of(analysis.counts))


class AnalysisListOut(BaseModel):
    items: list[AnalysisOut]
    total: int
    limit: int
    offset: int


# ── 결과 / 근거 ───────────────────────────────────────────────────────
# AP-05: 법적 근거 / 참고자료 / AI 해석을 응답에서도 분리된 객체로 유지한다.


class LegalEvidenceOut(BaseModel):
    """법제처 공식 근거. 이 블록의 값은 모델이 만든 것이 아니다."""

    law_id: str
    law_name: str
    article_no: str
    article_title: str | None
    effective_date: date | None
    ministry: str | None
    source_url: str | None
    quoted_spans: list[str] = Field(
        ..., description="원문 존재가 검증된 인용만 담긴다 (FR-021)"
    )


class ReferenceEvidenceOut(BaseModel):
    """RAG 참고자료. 법적 권위를 갖지 않는다."""

    doc_id: str
    title: str | None
    source: str
    agency: str | None
    published_at: date | None
    doc_type: DocType
    snippet: str


class ChecklistItemOut(BaseModel):
    title: str
    detail: str | None = None


class AiInterpretationOut(BaseModel):
    """AI 해석. 공식 사실값 필드가 없다 (FR-020)."""

    reason: str
    matched_conditions: list[str]
    missing_context: list[str]
    impact_summary: str | None
    affected_work: list[str]
    checklist: list[ChecklistItemOut]
    confidence: float | None
    model: str | None


class ChangeOut(BaseModel):
    change_type: ChangeType
    additions: list[str]
    deletions: list[str]
    delegation_targets: list[str]


class ValidationOut(BaseModel):
    passed: bool
    checks: dict[str, bool]
    failures: list[str]
    dropped_span_count: int = Field(
        ..., description="원문에서 확인되지 않아 제거된 인용 수"
    )


class ResultOut(BaseModel):
    result_id: str
    analysis_id: str | None
    status: ResultStatus
    applicability: Applicability
    action_grade: ActionGrade | None
    change: ChangeOut
    legal_evidence: LegalEvidenceOut
    reference_evidence: list[ReferenceEvidenceOut]
    ai_interpretation: AiInterpretationOut
    validation: ValidationOut
    created_at: datetime

    @classmethod
    def of(cls, result: AnalysisResult) -> ResultOut:
        return cls(
            result_id=result.result_id,
            analysis_id=result.analysis_id,
            status=result.status,
            applicability=result.applicability,
            action_grade=result.action_grade,
            change=ChangeOut(**result.change.model_dump()),
            legal_evidence=LegalEvidenceOut(
                **result.legal_evidence.model_dump(exclude={"kind"})
            ),
            reference_evidence=[
                ReferenceEvidenceOut(**r.model_dump(exclude={"kind"}))
                for r in result.reference_evidence
            ],
            ai_interpretation=AiInterpretationOut(
                **result.ai_interpretation.model_dump(exclude={"kind"})
            ),
            validation=ValidationOut(
                passed=result.validation.passed,
                checks=result.validation.checks,
                failures=result.validation.failures,
                dropped_span_count=len(result.validation.dropped_spans),
            ),
            created_at=result.created_at,
        )


class ResultListOut(BaseModel):
    analysis_id: str
    status: AnalysisStatus
    counts: CountsOut
    items: list[ResultOut]


class EvidenceOut(BaseModel):
    """FR-012/FR-014. 세 근거를 별도 키로 내보낸다. 프론트가 섞을 수 없다."""

    result_id: str
    legal_evidence: LegalEvidenceOut
    reference_evidence: list[ReferenceEvidenceOut]
    ai_interpretation: AiInterpretationOut
    disclaimer: str = Field(
        "이 서비스는 법률 자문이 아니라 AI 기반 규제 모니터링 도구입니다. "
        "AI 해석은 참고용이며, 법적 판단이 필요한 경우 전문가 검토를 받으십시오.",
        description="NFR-015",
    )


# ── 피드백 / 저장 ─────────────────────────────────────────────────────


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    helpful: bool
    correction_type: str | None = Field(None, max_length=50)
    comment: str | None = Field(None, max_length=2000)


class FeedbackOut(BaseModel):
    feedback_id: str
    result_id: str
    helpful: bool
    correction_type: str | None
    comment: str | None
    created_at: datetime


class SavedRegulationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str
    note: str | None = Field(None, max_length=2000)


class SavedRegulationOut(BaseModel):
    saved_id: str
    result_id: str
    law_id: str
    law_name: str
    article_no: str
    note: str | None
    created_at: datetime
