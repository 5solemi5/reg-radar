"""신구법 비교 파서 테스트 (FR-005, BR-002).

fixture는 법제처 실제 응답이다 (근로기준법, 2025-10-01 → 2026-08-20 개정).
"""

import datetime as dt

import pytest

from app.adapters.law.oldnew import (
    extract_change_marks,
    is_placeholder_only,
    parse_old_and_new,
    strip_change_marks,
)
from app.adapters.law.parser import LawParseError
from app.diff.engine import change_from_official_marks
from app.domain.enums import ChangeType
from tests.conftest import load_fixture


class TestChangeMarks:
    def test_변경구간_추출(self):
        assert extract_change_marks("① <P>제19조에 따른</P> 육아휴직") == ["제19조에 따른"]

    def test_여러_구간(self):
        text = "<P>가</P> 중간 <P>나</P>"
        assert extract_change_marks(text) == ["가", "나"]

    def test_표시가_없으면_빈_목록(self):
        assert extract_change_marks("변경 없는 조문") == []

    def test_태그만_제거하고_내용은_보존(self):
        assert strip_change_marks("① <P>제19조에 따른</P> 휴직") == "① 제19조에 따른 휴직"


class TestPlaceholder:
    @pytest.mark.parametrize(
        "text",
        [
            "① ∼ ⑤ (생  략)",
            "1.·2. (생  략)",
            "⑦ (현행과 같음)",
            "④·⑤ (생  략)",
            "①·② (생  략)",
        ],
    )
    def test_자리표시자_인식(self, text):
        assert is_placeholder_only(text)

    @pytest.mark.parametrize(
        "text",
        [
            "제60조(연차 유급휴가) ① ∼ ⑤ (생  략)",
            "⑥ 제1항 및 제2항을 적용하는 경우 다음 각 호의 기간은 출근한 것으로 본다.",
            "3. 「남녀고용평등법」 제19조에 따른 육아휴직으로 휴업한 기간",
        ],
    )
    def test_실질_내용이_있으면_자리표시자가_아니다(self, text):
        assert not is_placeholder_only(text)


class TestParseRealResponse:
    @pytest.fixture
    def comparison(self):
        return parse_old_and_new(load_fixture("law_oldnew.xml"))

    def test_버전_메타(self, comparison):
        assert comparison.law_name == "근로기준법"
        assert comparison.old_version.effective_date == dt.date(2025, 10, 1)
        assert comparison.new_version.effective_date == dt.date(2026, 8, 20)
        assert comparison.new_version.is_current
        assert not comparison.old_version.is_current

    def test_변경된_조문만_반환한다(self, comparison):
        """이 응답의 핵심 가치 — 132개 조문 중 실제 바뀐 것만 온다."""
        assert comparison.changed_article_numbers == ["제60조"]

    def test_조문_제목(self, comparison):
        assert comparison.changed_articles[0].article_title == "연차 유급휴가"

    def test_변경_구간이_정확히_잡힌다(self, comparison):
        article = comparison.changed_articles[0]
        assert article.deletions == ["제19조제1항에 따른"]
        assert article.additions == ["제19조에 따른"]

    def test_내용없이_생략만_표시한_줄은_버려진다(self, comparison):
        """'1.·2. (생  략)', '⑦ (생  략)' 처럼 실질 내용이 없는 줄은 제외한다."""
        article = comparison.changed_articles[0]
        for noise in ("1.·2.", "4.·5.", "⑦"):
            assert noise not in article.old_text

    def test_조문_머리글은_보존된다(self, comparison):
        """머리글의 '(생 략)'은 법제처 신구법대조표의 실제 표기이므로 손대지 않는다.
        임의로 지우면 공식 자료를 왜곡하게 된다.
        """
        article = comparison.changed_articles[0]
        assert article.old_text.startswith("제60조(연차 유급휴가)")
        assert article.new_text.startswith("제60조(연차 유급휴가)")

    def test_구버전과_신버전이_해당_구간에서_다르다(self, comparison):
        article = comparison.changed_articles[0]
        assert "제19조제1항에 따른" in article.old_text
        assert "제19조에 따른" in article.new_text
        assert "제19조제1항에 따른" not in article.new_text

    def test_본문에는_실제_내용이_남는다(self, comparison):
        article = comparison.changed_articles[0]
        assert "육아휴직으로 휴업한 기간" in article.new_text

    def test_잘못된_루트는_예외(self):
        with pytest.raises(LawParseError, match="예상치 못한 응답 루트"):
            parse_old_and_new("<Wrong/>")


class TestChangeContextFromMarks:
    def test_개정(self):
        c = change_from_official_marks(
            before_text="제19조제1항에 따른 육아휴직",
            after_text="제19조에 따른 육아휴직",
            additions=["제19조에 따른"],
            deletions=["제19조제1항에 따른"],
        )
        assert c.change_type is ChangeType.AMENDED
        assert c.additions == ["제19조에 따른"]
        assert c.deletions == ["제19조제1항에 따른"]

    def test_신설(self):
        c = change_from_official_marks(
            before_text=None, after_text="새 조문", additions=["새 조문"], deletions=[]
        )
        assert c.change_type is ChangeType.NEW

    def test_삭제(self):
        c = change_from_official_marks(
            before_text="옛 조문", after_text=None, additions=[], deletions=["옛 조문"]
        )
        assert c.change_type is ChangeType.DELETED

    def test_위임은_개정후_기준으로_감지(self):
        c = change_from_official_marks(
            before_text="기존 내용",
            after_text="필요한 사항은 대통령령으로 정한다.",
            additions=["대통령령으로 정한다"],
            deletions=[],
        )
        assert c.delegation_targets == ["대통령령"]

    def test_추정_diff와_달리_표시된_구간만_쓴다(self):
        """compute_change는 문장 단위로 추정하지만, 이쪽은 법제처 표시를 그대로 쓴다."""
        c = change_from_official_marks(
            before_text="아주 긴 조문 전체 텍스트입니다. 그 중 일부만 바뀝니다.",
            after_text="아주 긴 조문 전체 텍스트입니다. 그 중 일부분만 바뀝니다.",
            additions=["일부분"],
            deletions=["일부"],
        )
        assert c.additions == ["일부분"]
        assert len(c.additions) == 1
