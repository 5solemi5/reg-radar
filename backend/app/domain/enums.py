"""도메인 전역 enum. BR-007에 따라 '적용 판정'과 '행동 등급'은 서로 다른 축으로 관리한다."""

from enum import StrEnum


class Applicability(StrEnum):
    """FR-007. 사용자 프로필 대비 법령 적용 여부."""

    APPLICABLE = "APPLICABLE"
    HOLD = "HOLD"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ActionGrade(StrEnum):
    """FR-010. 대응 우선순위. HOLD 결과에는 부여하지 않는다."""

    ACTION = "ACTION"
    DECISION = "DECISION"
    AWARENESS = "AWARENESS"


class ChangeType(StrEnum):
    """FR-005. Diff Engine이 코드로 계산한 변경 유형 (LLM 생성 금지)."""

    NEW = "NEW"
    AMENDED = "AMENDED"
    DELETED = "DELETED"
    UNCHANGED = "UNCHANGED"


class AnalysisStatus(StrEnum):
    """04 설계서 §10-1 분석 상태 머신."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResultStatus(StrEnum):
    """04 설계서 §10-1 개별 결과 상태 머신."""

    PENDING = "PENDING"
    GENERATED = "GENERATED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    HOLD = "HOLD"
    REJECTED = "REJECTED"


class CompanySize(StrEnum):
    """규모 조건 판단용. '사업자' 표현만 보고 규모를 놓친 오탐(기획서 §2)을 막기 위한 축."""

    SOLO = "SOLO"           # 1인 사업자
    MICRO = "MICRO"         # 5인 미만
    SMALL = "SMALL"         # 5~49인
    MEDIUM = "MEDIUM"       # 50~299인
    LARGE = "LARGE"         # 300인 이상


class DocType(StrEnum):
    """RAG 문서 유형 (FR-013 metadata)."""

    GUIDE = "GUIDE"                 # 정부기관 가이드
    FAQ = "FAQ"                     # FAQ
    INTERPRETATION = "INTERPRETATION"  # 행정해석
    PRESS = "PRESS"                 # 보도자료
    CASE = "CASE"                   # 검증된 사례/결정례


class EvidenceKind(StrEnum):
    """AP-05. 근거의 성격을 절대 섞지 않기 위한 구분자."""

    OFFICIAL_LAW = "OFFICIAL_LAW"   # 법제처 원문 — 법적 근거
    RAG_REFERENCE = "RAG_REFERENCE" # RAG 참고자료 — 실무 맥락
    AI_INTERPRETATION = "AI_INTERPRETATION"  # AI 해석
