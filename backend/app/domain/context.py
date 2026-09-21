"""LLM 입력 Context 객체 (04 설계서 §6-2).

이 계층의 값은 모두 deterministic layer(프로필 서비스 / 법제처 어댑터 / Diff 엔진 /
Retriever)가 생성한다. LLM은 여기에 쓰기 권한이 없다 (AP-01, BR-001).
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ChangeType, CompanySize, DocType


class UserContext(BaseModel):
    """생성 주체: Profile Service."""

    model_config = ConfigDict(frozen=True)

    job: str = Field(..., description="직무. 예: HR 담당자, 백엔드 개발자, 쇼핑몰 운영")
    industry: str = Field(..., description="업종. 예: 이커머스, IT 서비스, 제조")
    company_size: CompanySize
    employee_count: int | None = Field(
        None, description="상시근로자 수. 없으면 규모 조건에서 HOLD 사유가 될 수 있다."
    )
    interests: list[str] = Field(default_factory=list, description="관심 규제 영역")

    def to_prompt_block(self) -> str:
        headcount = self.employee_count if self.employee_count is not None else "미상"
        lines = [
            f"- 직무: {self.job}",
            f"- 업종: {self.industry}",
            f"- 회사 규모: {self.company_size.value}",
            f"- 상시근로자 수: {headcount}",
            f"- 관심 영역: {', '.join(self.interests) if self.interests else '없음'}",
        ]
        return "\n".join(lines)


class LegalContext(BaseModel):
    """생성 주체: Legal Data Adapter (법제처 OPEN API).

    여기 담긴 필드는 전부 '공식 사실값'이며 LLM 출력으로 대체될 수 없다 (BR-001).
    """

    model_config = ConfigDict(frozen=True)

    law_id: str = Field(..., description="법령 ID 또는 MST")
    law_name: str
    article_no: str = Field(..., description="조문번호. 예: 제15조의2")
    article_title: str | None = None
    effective_date: date | None = Field(None, description="시행일")
    promulgation_date: date | None = Field(None, description="공포일")
    ministry: str | None = Field(None, description="소관 기관")
    original_text: str = Field(..., description="조문 원문. 인용 검증(FR-021)의 기준 문자열")
    source_url: str | None = Field(None, description="법제처 공식 URL")

    def to_prompt_block(self) -> str:
        return (
            f"- 법령명: {self.law_name}\n"
            f"- 조문: {self.article_no}"
            f"{' ' + self.article_title if self.article_title else ''}\n"
            f"- 시행일: {self.effective_date.isoformat() if self.effective_date else '미상'}\n"
            f"- 소관: {self.ministry or '미상'}\n"
            f"- 조문 원문:\n{self.original_text}"
        )


class ChangeContext(BaseModel):
    """생성 주체: Diff Engine. LLM은 여기 없는 변화를 만들어낼 수 없다 (BR-002)."""

    model_config = ConfigDict(frozen=True)

    change_type: ChangeType
    before_text: str | None = None
    after_text: str | None = None
    additions: list[str] = Field(default_factory=list, description="추가된 문장/구")
    deletions: list[str] = Field(default_factory=list, description="삭제된 문장/구")
    delegation_targets: list[str] = Field(
        default_factory=list,
        description="시행령·시행규칙 등 하위법령 위임 문자열 (AP-03, Q5). 존재 시 HOLD 근거.",
    )

    @property
    def has_delegation(self) -> bool:
        return bool(self.delegation_targets)

    def to_prompt_block(self) -> str:
        if self.change_type is ChangeType.NEW:
            head = "- 변경 유형: 신설"
        elif self.change_type is ChangeType.DELETED:
            head = "- 변경 유형: 삭제"
        elif self.change_type is ChangeType.AMENDED:
            head = "- 변경 유형: 개정"
        else:
            head = "- 변경 유형: 변경 없음"
        lines = [head]
        if self.additions:
            lines.append("- 추가된 내용:\n" + "\n".join(f"  + {a}" for a in self.additions))
        if self.deletions:
            lines.append("- 삭제된 내용:\n" + "\n".join(f"  - {d}" for d in self.deletions))
        if self.delegation_targets:
            lines.append("- 하위법령 위임: " + ", ".join(self.delegation_targets))
        return "\n".join(lines)


class RagContext(BaseModel):
    """생성 주체: Retriever. 법적 근거가 아니라 '참고 맥락'이다 (AP-05, BR-004)."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    source: str = Field(..., description="문서 출처 URL 또는 식별자")
    agency: str | None = Field(None, description="발행 기관")
    published_at: date | None = None
    doc_type: DocType
    title: str | None = None
    snippet: str = Field(..., description="검색된 본문 조각")
    score: float | None = None

    def to_prompt_block(self, index: int) -> str:
        meta = " · ".join(
            x
            for x in (
                self.agency,
                self.doc_type.value,
                self.published_at.isoformat() if self.published_at else None,
            )
            if x
        )
        return f"[R{index}] ({meta}) {self.title or ''}\n{self.snippet}"


class ContextPacket(BaseModel):
    """생성 주체: Context Builder. AI Core로 들어가는 유일한 입력 단위."""

    model_config = ConfigDict(frozen=True)

    user: UserContext
    law: LegalContext
    change: ChangeContext
    rag: list[RagContext] = Field(default_factory=list)

    @property
    def has_rag(self) -> bool:
        """BR-005. RAG 0건은 정상 상태이며 LLM이 출처를 지어내면 안 된다."""
        return bool(self.rag)
