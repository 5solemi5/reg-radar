"""예시 프로필 — 02 페르소나 문서의 P01~P03을 그대로 옮긴 것.

처음 쓰는 사람이 직무·업종·규모에 활동 8개까지 채워야 첫 화면을 볼 수 있다.
데모나 심사에서는 그 입력이 서비스를 보기 전에 포기하게 만드는 문턱이다.
한 번 눌러 채우고 바로 분석까지 가게 한다.

**프리셋 정의를 백엔드에 두는 이유**는 활동 코드 때문이다. 프론트에 두면 코드가
바뀌었을 때 프리셋이 조용히 빈 값을 채운다 — 화면은 멀쩡한데 판정만 달라지므로
알아채기 어렵다. 여기 두면 `BusinessActivity` 타입이 그것을 막는다.

각 프리셋에 **답하지 않은 활동을 하나씩 남겨 두었다.** 전부 채우면 보류가 거의
나오지 않아 이 서비스의 핵심인 '보류 → 재판정'(FR-008)을 볼 수 없다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ActivityAnswer, BusinessActivity, CompanySize

Y = ActivityAnswer.YES
N = ActivityAnswer.NO


class ProfilePreset(BaseModel):
    """온보딩에서 한 번에 채울 수 있는 예시 프로필."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str = Field(..., description="버튼에 쓰는 이름")
    summary: str = Field(..., description="어떤 사람인지 한 줄")
    job: str
    industry: str
    company_size: CompanySize
    employee_count: int | None
    interests: list[str]
    activities: dict[BusinessActivity, ActivityAnswer]


PROFILE_PRESETS: tuple[ProfilePreset, ...] = (
    ProfilePreset(
        key="p01_commerce",
        label="P01 김민지 — 온라인 쇼핑몰 대표",
        summary="직원 4명. 법무 담당자가 없고 '이 법이 우리한테도 적용되나'가 늘 질문이다.",
        job="쇼핑몰 운영·총무 (상품·마케팅·고객응대·직원관리)",
        industry="이커머스 소매",
        company_size=CompanySize.MICRO,
        employee_count=4,
        interests=["개인정보", "전자상거래", "노동·인사"],
        activities={
            BusinessActivity.ONLINE_SALES: Y,
            BusinessActivity.INFO_SERVICE: Y,
            BusinessActivity.SUBCONTRACTING: N,
            BusinessActivity.FOREIGN_WORKERS: N,
            BusinessActivity.DISPATCH_WORKERS: N,
            BusinessActivity.HAZARDOUS_CHEMICALS: N,
            BusinessActivity.FOOD_BUSINESS: N,
            # 사업장폐기물은 일부러 비워 둔다 — 보류와 재판정을 보여주기 위해서다.
        },
    ),
    ProfilePreset(
        key="p02_it_hr",
        label="P02 박준호 — IT기업 HR 실무자",
        summary="직원 80명. 개정 사실은 알아도 어떤 규정·양식을 고쳐야 하는지가 어렵다.",
        job="HR 담당자 (채용·근태·급여·근로계약·취업규칙)",
        industry="IT 서비스",
        company_size=CompanySize.MEDIUM,
        employee_count=80,
        interests=["노동·인사", "개인정보"],
        activities={
            BusinessActivity.SUBCONTRACTING: Y,
            BusinessActivity.INFO_SERVICE: Y,
            BusinessActivity.ONLINE_SALES: N,
            BusinessActivity.WORKPLACE_WASTE: N,
            BusinessActivity.DISPATCH_WORKERS: N,
            BusinessActivity.HAZARDOUS_CHEMICALS: N,
            BusinessActivity.FOOD_BUSINESS: N,
            # 외국인근로자 고용은 비워 둔다.
        },
    ),
    ProfilePreset(
        key="p03_manufacturing",
        label="P03 이수현 — 제조기업 운영팀장",
        summary="직원 150명. 한꺼번에 쏟아지는 규제 중 무엇을 먼저 대응할지가 문제다.",
        job="운영·경영지원 팀장 (정책·리스크·부서 조율)",
        industry="제조",
        company_size=CompanySize.MEDIUM,
        employee_count=150,
        interests=["안전·보건", "노동·인사", "환경"],
        activities={
            BusinessActivity.SUBCONTRACTING: Y,
            BusinessActivity.WORKPLACE_WASTE: Y,
            BusinessActivity.FOREIGN_WORKERS: Y,
            BusinessActivity.DISPATCH_WORKERS: Y,
            BusinessActivity.ONLINE_SALES: N,
            BusinessActivity.INFO_SERVICE: N,
            BusinessActivity.FOOD_BUSINESS: N,
            # 유해화학물질 취급은 비워 둔다.
        },
    ),
)
