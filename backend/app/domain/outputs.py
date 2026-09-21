"""LLM Structured Output 스키마 (FR-006, FR-007, FR-009, FR-010).

FR-020 설계 원칙: 이 스키마에는 공식 사실 필드(법령명·조문번호·시행일·기관·URL)를
**아예 두지 않는다**. 모델이 값을 담을 자리가 없으면 위조도 불가능하다.
모델이 원문을 참조해야 할 때는 `cited_spans`(원문에서 그대로 복사한 문자열)만 허용하고,
그 문자열은 Validator가 snapshot 원문 substring인지 검증한다 (FR-021).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ActionGrade, Applicability

# 이 문자열 중 하나라도 LLM 출력 스키마의 필드명으로 등장하면 설계 위반이다.
FORBIDDEN_FACT_FIELDS: frozenset[str] = frozenset(
    {
        "law_id",
        "law_name",
        "article_no",
        "article_title",
        "effective_date",
        "promulgation_date",
        "ministry",
        "source_url",
        "original_text",
    }
)


class TargetCondition(BaseModel):
    """C3. 조문에서 추출한 적용대상 조건 하나."""

    description: str = Field(..., description="적용대상/조건을 한 문장으로 서술")
    kind: str = Field(
        ...,
        description=(
            "조건 축. industry(업종) | size(규모) | job(직무/업무) "
            "| activity(행위) | other"
        ),
    )
    is_required: bool = Field(
        ..., description="충족하지 않으면 적용되지 않는 필수 조건이면 true, 예외/단서면 false"
    )
    cited_span: str = Field(
        ...,
        description=(
            "이 조건의 근거가 되는 조문 원문 구절을 **그대로 복사**한 문자열. 요약·변형 금지."
        ),
    )


class TargetExtractionOutput(BaseModel):
    """C3 Chain 출력. 적용대상 구조화 추출."""

    model_config = ConfigDict(extra="forbid")

    conditions: list[TargetCondition] = Field(default_factory=list)
    exceptions: list[str] = Field(
        default_factory=list, description="조문에 명시된 적용 제외/단서 사항"
    )
    missing_context: list[str] = Field(
        default_factory=list,
        description="조문만으로 확정할 수 없어 추가 확인이 필요한 요소 (예: 상시근로자 수 기준)",
    )

    @property
    def cited_spans(self) -> list[str]:
        return [c.cited_span for c in self.conditions]


class ApplicabilityOutput(BaseModel):
    """C4 Chain 출력. 사용자 ↔ 법령 매핑 판정 (FR-007)."""

    model_config = ConfigDict(extra="forbid")

    applicability: Applicability
    reason: str = Field(..., description="왜 그렇게 판정했는지. 사용자 프로필과의 연결을 명시.")
    matched_conditions: list[str] = Field(
        default_factory=list, description="사용자 프로필과 연결된 적용조건 서술"
    )
    missing_context: list[str] = Field(
        default_factory=list,
        description="HOLD인 경우 무엇을 알아야 확정할 수 있는지. HOLD면 비어 있을 수 없다.",
    )
    cited_spans: list[str] = Field(
        default_factory=list, description="판정 근거로 인용한 조문 원문 구절 (원문 그대로)"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _hold_requires_missing_context(self) -> "ApplicabilityOutput":
        # BR-003 / FR-007: HOLD는 '무엇이 부족한지'를 반드시 말해야 한다.
        if self.applicability is Applicability.HOLD and not self.missing_context:
            raise ValueError("HOLD 판정은 missing_context를 최소 1개 포함해야 합니다.")
        return self


class ChecklistItem(BaseModel):
    """FR-011. 실행 체크리스트 항목. 법령 사실값과 분리된 필드로 관리한다."""

    title: str
    detail: str | None = None


class ImpactOutput(BaseModel):
    """C5 Chain 출력. 실무 영향 + 행동 등급 (FR-009, FR-010)."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., description="이 변화가 이 사용자에게 무엇을 의미하는지 2~3문장")
    affected_work: list[str] = Field(
        default_factory=list, description="영향을 받는 업무·프로세스·내부 문서"
    )
    action_grade: ActionGrade
    action_grade_reason: str
    checklist: list[ChecklistItem] = Field(
        default_factory=list, description="근거가 없으면 억지로 생성하지 않는다 (FR-011)."
    )
    cited_spans: list[str] = Field(default_factory=list)


def assert_no_forbidden_fields(model: type[BaseModel]) -> None:
    """LLM 출력 스키마가 공식 사실 필드를 갖지 않는지 구조적으로 검사한다 (FR-020, NFR-004)."""
    leaked = FORBIDDEN_FACT_FIELDS & set(model.model_fields)
    if leaked:
        raise AssertionError(
            f"{model.__name__}에 금지된 공식 사실 필드가 있습니다: {sorted(leaked)}"
        )
