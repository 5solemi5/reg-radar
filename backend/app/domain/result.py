"""분석 결과 도메인 모델.

AP-05 / FR-014: 근거를 세 종류로 **필드 수준에서 분리**한다.
  legal_evidence     — 법제처 원문 (법적 근거)
  delegated_evidence — 위임된 하위법령 원문 (법적 근거, 모법과 분리)
  reference_evidence — RAG 참고자료 (실무 맥락)
  ai_interpretation  — LLM 해석 (검증 통과분만)
UI는 이 구분을 그대로 렌더링하면 되고, 데이터가 섞일 여지가 없다.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    ActionGrade,
    Applicability,
    ChangeType,
    DocType,
    EvidenceKind,
    ResultStatus,
)
from app.domain.outputs import ChecklistItem


class LegalEvidence(BaseModel):
    """법적 근거. 전부 법제처 snapshot에서만 채워진다 (BR-001)."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind = EvidenceKind.OFFICIAL_LAW
    law_id: str
    law_name: str
    article_no: str
    article_title: str | None = None
    effective_date: date | None = None
    ministry: str | None = None
    source_url: str | None = None
    quoted_spans: list[str] = Field(
        default_factory=list,
        description="AI가 인용했고 Validator가 원문 substring임을 확인한 구절만 담긴다.",
    )


class DelegatedEvidence(BaseModel):
    """위임된 하위법령 근거 (ADR-025). 법적 근거지만 **모법 조문이 아니다**.

    모법 인용과 한 칸에 섞으면 시행령 구절이 모법 조문에서 나온 것처럼 보인다.
    사용자가 원문을 대조할 때 찾을 수 없는 문장을 보게 되므로 BR-001 위반이다.
    """

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind = EvidenceKind.OFFICIAL_LAW
    law_id: str
    law_name: str = Field(..., description="하위법령명. 예: 최저임금법 시행령")
    law_type: str | None = None
    article_no: str
    article_title: str | None = None
    source_url: str | None = None
    quoted_spans: list[str] = Field(default_factory=list)
    resolves_criterion: bool = Field(
        True, description="False면 이 조문이 기준을 별표 등으로 다시 넘긴다는 뜻이다."
    )


class ReferenceEvidence(BaseModel):
    """RAG 참고자료. 법적 권위를 갖지 않는다 (BR-004)."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind = EvidenceKind.RAG_REFERENCE
    doc_id: str
    title: str | None = None
    source: str
    agency: str | None = None
    published_at: date | None = None
    doc_type: DocType
    snippet: str


class AiInterpretation(BaseModel):
    """AI 해석. 공식 사실값을 담지 않는다 (FR-020)."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind = EvidenceKind.AI_INTERPRETATION
    reason: str
    matched_conditions: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    impact_summary: str | None = None
    affected_work: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    confidence: float | None = None
    model: str | None = None


class ChangeSummary(BaseModel):
    """Diff Engine 산출물의 표시용 요약 (BR-002)."""

    model_config = ConfigDict(frozen=True)

    change_type: ChangeType
    additions: list[str] = Field(default_factory=list)
    deletions: list[str] = Field(default_factory=list)
    delegation_targets: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """C6 Validator 결과. NFR-009 관측 대상."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    dropped_spans: list[str] = Field(
        default_factory=list, description="원문에서 확인되지 않아 제거된 인용"
    )
    downgraded_to_hold: bool = False


class AnalysisResult(BaseModel):
    """법령 1건에 대한 최종 결과. analysis_results 테이블에 대응한다."""

    result_id: str = Field(default_factory=lambda: str(uuid4()))
    analysis_id: str | None = None
    status: ResultStatus = ResultStatus.PENDING

    # 판정 축과 행동 축은 분리 (BR-007)
    applicability: Applicability
    action_grade: ActionGrade | None = None

    change: ChangeSummary
    legal_evidence: LegalEvidence
    delegated_evidence: list[DelegatedEvidence] = Field(
        default_factory=list,
        description="위임된 하위법령 근거 (ADR-025). 모법 근거와 분리해 표시한다.",
    )
    reference_evidence: list[ReferenceEvidence] = Field(default_factory=list)
    ai_interpretation: AiInterpretation

    validation: ValidationReport
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_displayable(self) -> bool:
        """FR-022. 검증 실패 결과는 정상 결과로 노출하지 않는다."""
        return self.status in (ResultStatus.VALIDATED, ResultStatus.HOLD)
