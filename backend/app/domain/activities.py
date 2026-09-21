"""사업 활동 질문 정의 — 백엔드가 유일한 출처다 (ADR-033).

프론트엔드가 같은 문구를 따로 들고 있으면 반드시 어긋난다. 코드가 8개인데
화면에 7개만 있어도 아무도 모르고, 사용자는 답할 기회조차 없는 질문 때문에
보류를 받는다. 그래서 목록을 API로 내보내고 화면은 그것을 그린다.

각 질문은 **사용자가 사실로 답할 수 있는 형태**여야 한다. "귀사가 원사업자입니까"는
법률 용어를 아는 사람만 답할 수 있다. "제조·공사·용역을 다른 사업자에게 맡기십니까"로
묻는다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import BusinessActivity


class ActivityQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity: BusinessActivity
    question: str = Field(..., description="사용자에게 보여줄 질문. 법률 용어를 쓰지 않는다")
    hint: str = Field(..., description="판단을 돕는 한 줄. 예시를 준다")
    label: str = Field(..., description="프롬프트·요약에 쓰는 짧은 이름")


ACTIVITY_QUESTIONS: tuple[ActivityQuestion, ...] = (
    ActivityQuestion(
        activity=BusinessActivity.SUBCONTRACTING,
        question="제조·공사·용역의 일부를 다른 사업자에게 맡기십니까?",
        hint="외주 개발, 생산 위탁, 공사 하도급 등이 해당합니다.",
        label="도급·위탁",
    ),
    ActivityQuestion(
        activity=BusinessActivity.FOREIGN_WORKERS,
        question="외국인근로자를 고용하고 있습니까?",
        hint="고용허가제(E-9 등)로 채용한 인력이 있으면 '예'입니다.",
        label="외국인근로자 고용",
    ),
    ActivityQuestion(
        activity=BusinessActivity.ONLINE_SALES,
        question="소비자에게 온라인으로 재화나 서비스를 판매합니까?",
        hint="자사몰, 오픈마켓 입점, 앱 내 결제 등이 해당합니다.",
        label="통신판매",
    ),
    ActivityQuestion(
        activity=BusinessActivity.INFO_SERVICE,
        question="웹사이트·앱 등 온라인 서비스를 직접 운영합니까?",
        hint="회사 소개 페이지만 있는 경우는 보통 해당하지 않습니다.",
        label="정보통신서비스 제공",
    ),
    ActivityQuestion(
        activity=BusinessActivity.WORKPLACE_WASTE,
        question="사업장에서 폐기물이 발생합니까?",
        hint="생산 공정 폐기물, 지정폐기물, 일정량 이상의 사업장 일반폐기물을 말합니다.",
        label="사업장폐기물 배출",
    ),
    ActivityQuestion(
        activity=BusinessActivity.DISPATCH_WORKERS,
        question="파견근로자를 사용하거나 파견사업을 운영합니까?",
        hint="파견업체에서 인력을 받아 쓰는 경우도 포함합니다.",
        label="근로자파견",
    ),
    ActivityQuestion(
        activity=BusinessActivity.HAZARDOUS_CHEMICALS,
        question="유해화학물질을 제조·수입·판매·보관하거나 사용합니까?",
        hint="유독물질, 허가물질, 사고대비물질 등입니다.",
        label="유해화학물질 취급",
    ),
    ActivityQuestion(
        activity=BusinessActivity.FOOD_BUSINESS,
        question="식품을 제조·가공·조리하거나 판매합니까?",
        hint="구내식당 운영, 식품 유통도 해당할 수 있습니다.",
        label="식품 취급",
    ),
)

QUESTION_BY_ACTIVITY: dict[BusinessActivity, ActivityQuestion] = {
    q.activity: q for q in ACTIVITY_QUESTIONS
}
