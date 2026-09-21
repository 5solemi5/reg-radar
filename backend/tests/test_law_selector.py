"""법령 선정 테스트 (FR-003).

회귀 배경: 시행일 내림차순으로 최신 N건만 집었더니 IT 서비스 HR 담당자에게
'감사원사무처 직제', '하천법 시행규칙'이 분석 대상으로 나왔다. 판정은 정확히
'무관'이었지만 볼 필요 없는 것을 분석하느라 비용만 썼다.
"""

import pytest

from app.adapters.law.models import LawSummary
from app.services.law_selector import (
    FALLBACK_KEYWORDS,
    build_search_keywords,
    dedupe_laws,
)


class TestKeywordsFromInterests:
    def test_관심영역이_검색어로_바뀐다(self):
        keywords = build_search_keywords(
            interests=["노동·인사"], industry="IT 서비스", job="HR 담당자"
        )
        assert "근로기준법" in keywords

    def test_분류어_자체는_검색어로_쓰지_않는다(self):
        """'노동·인사'는 법령명이 아니라 분류어다. 그대로 검색하면 0건이 나온다."""
        keywords = build_search_keywords(
            interests=["노동·인사"], industry="IT 서비스"
        )
        assert "노동·인사" not in keywords

    def test_여러_관심영역이_모두_반영된다(self):
        keywords = build_search_keywords(
            interests=["노동·인사", "개인정보"], industry="제조"
        )
        assert "근로기준법" in keywords
        assert "개인정보 보호법" in keywords

    def test_관심영역이_업종보다_앞선다(self):
        """사용자가 직접 고른 것이 유추한 것보다 우선이다."""
        keywords = build_search_keywords(interests=["세무·회계"], industry="제조")
        assert keywords.index("소득세법") < keywords.index("산업안전보건법")


class TestKeywordsFromIndustry:
    @pytest.mark.parametrize(
        "industry,expected",
        [
            ("이커머스 소매", "전자상거래"),
            ("제조", "산업안전보건법"),
            ("IT 서비스", "개인정보 보호법"),
            ("식품 제조", "식품위생법"),
            ("건설", "중대재해 처벌"),
        ],
    )
    def test_업종에서_유추한다(self, industry, expected):
        assert expected in build_search_keywords(interests=[], industry=industry)

    def test_대소문자를_가리지_않는다(self):
        assert "개인정보 보호법" in build_search_keywords(interests=[], industry="IT")
        assert "개인정보 보호법" in build_search_keywords(interests=[], industry="it")

    def test_직무_문자열도_참고한다(self):
        keywords = build_search_keywords(
            interests=[], industry="기타", job="플랫폼 운영 담당"
        )
        assert "전자상거래" in keywords


class TestFallback:
    def test_아무것도_안_걸리면_기본_후보를_쓴다(self):
        """빈손으로 끝나면 사용자는 '분석했는데 아무것도 없다'를 보게 된다."""
        keywords = build_search_keywords(interests=[], industry="알 수 없음", job="")
        assert keywords == list(FALLBACK_KEYWORDS)

    def test_중복_검색어는_한_번만(self):
        keywords = build_search_keywords(
            interests=["개인정보"], industry="IT 서비스"
        )
        assert keywords.count("개인정보 보호법") == 1


class TestDedupeLaws:
    def _law(self, law_id: str, mst: str | None, name: str) -> LawSummary:
        return LawSummary(law_id=law_id, mst=mst, law_name=name)

    def test_같은_MST는_한_번만(self):
        laws = [
            self._law("1", "100", "근로기준법"),
            self._law("1", "100", "근로기준법"),
            self._law("2", "200", "개인정보 보호법"),
        ]
        assert len(dedupe_laws(laws)) == 2

    def test_MST가_없으면_law_id로_구분한다(self):
        laws = [self._law("1", None, "법A"), self._law("1", None, "법A")]
        assert len(dedupe_laws(laws)) == 1

    def test_순서가_유지된다(self):
        laws = [
            self._law("1", "100", "근로기준법"),
            self._law("2", "200", "개인정보 보호법"),
        ]
        assert [law.law_name for law in dedupe_laws(laws)] == [
            "근로기준법", "개인정보 보호법",
        ]
