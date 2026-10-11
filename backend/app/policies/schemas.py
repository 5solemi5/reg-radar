"""C7·C8 LLM 출력 스키마 — 사내 규정 영향 매핑, 개정 초안 (문서 12 §4).

`app/domain/outputs.py`와 같은 원칙(FR-020): 사실 필드(규정 ID·조문번호·법령명·원문)를
두지 않는다. LLM은 후보 라벨(`P1`…)과 원문에서 그대로 복사한 인용만 쓴다.
라벨→규정 매핑과 원문은 코드가 갖고 있다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ImpactRelation(StrEnum):
    CONFLICT = "CONFLICT"  # 사내 규정이 법과 어긋난다 — 개정 필요
    # 어긋나지는 않지만 법의 요구를 담지 못했다 — 보완 필요
    UPDATE_RECOMMENDED = "UPDATE_RECOMMENDED"
    ALIGNED = "ALIGNED"  # 관련 있고 법과 부합한다 — 조치 불필요
    UNRELATED = "UNRELATED"  # 관련 없음


ACTIONABLE = frozenset({ImpactRelation.CONFLICT, ImpactRelation.UPDATE_RECOMMENDED})


class PolicyImpactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str = Field(..., pattern=r"^P\d+$", description="후보 라벨. 예: P2")
    relation: ImpactRelation
    reason: str = Field(..., description="판단 이유 1~2문장. 수치·조문은 인용으로만 근거를 댄다")
    cited_law_spans: list[str] = Field(
        default_factory=list, description="법령 조문 원문에서 그대로 복사한 구절"
    )
    cited_policy_spans: list[str] = Field(
        default_factory=list, description="해당 후보 사내 규정 원문에서 그대로 복사한 구절"
    )
    missing_context: list[str] = Field(
        default_factory=list, description="확정하려면 더 필요한 사실 (예: 대통령령 기준 해당 여부)"
    )


class PolicyImpactOutput(BaseModel):
    """C7. 후보 사내 규정 각각에 대한 영향 판단. 후보마다 정확히 하나."""

    model_config = ConfigDict(extra="forbid")

    items: list[PolicyImpactItem] = Field(default_factory=list)


class PolicyRevisionDraft(BaseModel):
    """C8. 사내 규정 개정 초안. 확정이 아니다 — 준법감시인이 승인해야 효력이 있다."""

    model_config = ConfigDict(extra="forbid")

    proposed_text: str = Field(..., description="개정 후 조문 본문 전체")
    change_summary: list[str] = Field(
        default_factory=list, description="무엇을 왜 바꿨는지 항목별 한 줄"
    )
    cited_law_spans: list[str] = Field(
        default_factory=list, description="개정 근거가 되는 법령 원문 구절(그대로 복사)"
    )
    open_questions: list[str] = Field(
        default_factory=list, description="담당자가 결정해야 할 사항 (예: 시행일, 경과조치)"
    )


class ReviewVerdict(StrEnum):
    CONFIRM = "CONFIRM"  # 개정이 필요하다 — 빠진 요구를 법 원문으로 짚었다
    DISPUTE = "DISPUTE"  # 규정이 이미 법의 의무를 담고 있거나, 이 조문이 다룰 일이 아니다


class ImpactReview(BaseModel):
    """C7b. 조치 대상 판단에 대한 반론 검토. 검토자는 '고칠 필요 없다'를 먼저 찾는다."""

    model_config = ConfigDict(extra="forbid")

    verdict: ReviewVerdict
    missing_requirement_spans: list[str] = Field(
        default_factory=list,
        description="CONFIRM일 때: 규정에 빠진 법의 구체 요구를 법령 원문에서 그대로 복사",
    )
    reason: str = Field(..., description="1~2문장")


LLM_POLICY_SCHEMAS = [PolicyImpactOutput, PolicyRevisionDraft, ImpactReview]
