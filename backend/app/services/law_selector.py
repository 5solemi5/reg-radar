"""분석 대상 법령 선정 (FR-003).

문제: 시행일 내림차순으로 최신 N건을 집으면 사용자와 무관한 법령이 대부분이다.
실측에서 IT 서비스 HR 담당자에게 '감사원사무처 직제', '하천법 시행규칙'이 나왔다.
AI 판정은 정확히 '무관'이었지만, 애초에 볼 필요 없는 것을 분석하느라 비용만 썼다.

해결: 프로필의 관심 영역과 업종을 법령명 검색어로 바꿔 후보를 좁힌다.
`interests`는 기획서 §9에서 '개인화 기준'으로 정의됐으나 그동안 쓰이지 않았다.

이 매핑은 규칙이지 추론이 아니다 (AP-03). LLM을 거치지 않는다.
"""

from __future__ import annotations

from app.adapters.law.models import LawSummary

# 관심 영역 → 법령명에 실제로 등장하는 검색어.
# 법제처 검색은 법령명 기준이므로 '노동·인사' 같은 분류어로는 걸리지 않는다.
INTEREST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "노동·인사": ("근로기준법", "근로자참여", "최저임금법", "남녀고용평등"),
    "개인정보": ("개인정보 보호법", "정보통신망"),
    "안전·보건": ("산업안전보건법", "중대재해 처벌"),
    "세무·회계": ("소득세법", "법인세법", "부가가치세법"),
    "전자상거래": ("전자상거래", "소비자기본법", "표시·광고"),
    "환경": ("환경정책기본법", "폐기물관리법", "화학물질관리법"),
    "식품·위생": ("식품위생법", "식품표시광고"),
    "금융": ("전자금융거래법", "신용정보"),
}

# 업종 문자열에 이 단어가 들어 있으면 해당 검색어를 추가한다.
INDUSTRY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("이커머스", ("전자상거래", "개인정보 보호법")),
    ("커머스", ("전자상거래", "개인정보 보호법")),
    ("쇼핑", ("전자상거래", "개인정보 보호법")),
    ("소매", ("전자상거래",)),
    ("유통", ("전자상거래",)),
    ("제조", ("산업안전보건법", "중대재해 처벌")),
    ("건설", ("산업안전보건법", "중대재해 처벌")),
    ("식품", ("식품위생법",)),
    ("요식", ("식품위생법",)),
    ("it", ("개인정보 보호법",)),
    ("소프트웨어", ("개인정보 보호법",)),
    ("플랫폼", ("개인정보 보호법", "전자상거래")),
    ("금융", ("전자금융거래법",)),
    ("의료", ("의료법",)),
    ("물류", ("산업안전보건법",)),
)

# 직무 무관하게 대부분의 사업자에게 걸리는 기본 후보.
# 관심 영역이 비어 있어도 빈손으로 끝나지 않게 한다.
FALLBACK_KEYWORDS: tuple[str, ...] = ("근로기준법", "개인정보 보호법", "산업안전보건법")


def build_search_keywords(
    *, interests: list[str], industry: str, job: str = ""
) -> list[str]:
    """프로필에서 법령 검색어를 만든다. 순서는 우선순위다."""
    keywords: list[str] = []

    def add(values: tuple[str, ...] | list[str]) -> None:
        for value in values:
            if value not in keywords:
                keywords.append(value)

    # 1순위: 사용자가 직접 고른 관심 영역
    for interest in interests:
        add(INTEREST_KEYWORDS.get(interest, ()))

    # 2순위: 업종에서 유추되는 영역
    haystack = f"{industry} {job}".lower()
    for needle, values in INDUSTRY_KEYWORDS:
        if needle in haystack:
            add(values)

    # 3순위: 아무것도 안 걸렸을 때의 기본값
    if not keywords:
        add(FALLBACK_KEYWORDS)

    return keywords


def dedupe_laws(laws: list[LawSummary]) -> list[LawSummary]:
    """여러 검색어의 결과를 합칠 때 같은 법령이 중복되지 않게 한다."""
    seen: set[str] = set()
    unique: list[LawSummary] = []
    for law in laws:
        key = law.mst or law.law_id
        if key not in seen:
            seen.add(key)
            unique.append(law)
    return unique


def pick_primary(laws: list[LawSummary], keyword: str) -> LawSummary | None:
    """검색 결과에서 대표 법령 1건을 고른다.

    '근로기준법'을 검색하면 시행령·시행규칙까지 함께 나온다. 이들을 모두 후보로
    담으면 첫 검색어가 예산을 다 써서 다른 관심 영역은 검색조차 되지 않는다.
    실측에서 '개인정보'를 관심 영역으로 골랐는데도 근로 관련 법령만 분석됐다.

    우선순위: 정확히 일치 > 시행령·시행규칙이 아닌 것 > 첫 결과.
    """
    if not laws:
        return None

    exact = next((law for law in laws if law.law_name == keyword), None)
    if exact is not None:
        return exact

    parent = next(
        (
            law
            for law in laws
            if not any(
                law.law_name.endswith(suffix)
                for suffix in ("시행령", "시행규칙", "규정", "규칙")
            )
        ),
        None,
    )
    return parent or laws[0]
