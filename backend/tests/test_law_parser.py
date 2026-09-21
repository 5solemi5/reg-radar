"""법제처 응답 파서 테스트 (FR-004 / BR-001)."""

import datetime as dt

import pytest

from app.adapters.law.parser import LawParseError, parse_law_detail, parse_law_list
from tests.conftest import load_fixture


class TestParseLawList:
    @pytest.fixture
    def laws(self):
        return parse_law_list(load_fixture("law_search.xml"))

    def test_유효항목만_파싱(self, laws):
        """법령ID/법령명이 없는 항목은 임의로 채우지 않고 버린다."""
        assert len(laws) == 2

    def test_필드_매핑(self, laws):
        law = laws[0]
        assert law.law_name == "근로자참여 및 협력증진에 관한 법률"
        assert law.law_id == "001766"
        assert law.mst == "265432"
        assert law.ministry == "고용노동부"
        assert law.effective_date == dt.date(2026, 9, 1)
        assert law.promulgation_date == dt.date(2026, 3, 10)
        assert law.revision_type == "일부개정"

    def test_본문조회키는_MST_우선(self, laws):
        assert laws[0].fetch_key == ("MST", "265432")

    def test_인증실패_응답은_예외(self):
        with pytest.raises(LawParseError, match="OC"):
            parse_law_list(load_fixture("law_error.xml"))


class TestParseLawDetail:
    @pytest.fixture
    def snapshot(self):
        return parse_law_detail(load_fixture("law_detail.xml"), source_url="https://example/law")

    def test_기본정보(self, snapshot):
        assert snapshot.law_id == "001766"
        assert snapshot.law_name == "근로자참여 및 협력증진에 관한 법률"
        assert snapshot.ministry == "고용노동부"
        assert snapshot.law_type == "법률"
        assert snapshot.effective_date == dt.date(2026, 9, 1)

    def test_조문번호_표기(self, snapshot):
        nos = [a.article_no for a in snapshot.articles if not a.is_supplementary]
        assert nos == ["제26조", "제27조의2"]

    def test_가지번호_0이면_의_표기를_붙이지_않는다(self, snapshot):
        assert snapshot.find_article("제26조") is not None
        assert snapshot.find_article("제26조의0") is None

    def test_항과_호가_원문에_모두_포함(self, snapshot):
        text = snapshot.find_article("제26조").original_text
        assert "① 모든 사업 또는 사업장에는" in text
        assert "② 고충처리위원의 선임과 운영에" in text
        assert "1. 고충처리위원의 임기" in text

    def test_부칙도_별도로_보존(self, snapshot):
        supp = [a for a in snapshot.articles if a.is_supplementary]
        assert len(supp) == 1
        assert "공포 후 6개월" in supp[0].original_text

    def test_기본정보_없으면_예외(self):
        with pytest.raises(LawParseError, match="기본정보"):
            parse_law_detail("<법령><조문/></법령>")


class TestToLegalContext:
    def test_공식_사실값이_그대로_전달된다(self):
        snapshot = parse_law_detail(load_fixture("law_detail.xml"), source_url="https://ex/law")
        ctx = snapshot.to_legal_context("제26조")
        assert ctx.law_name == snapshot.law_name
        assert ctx.article_no == "제26조"
        assert ctx.article_title == "고충처리위원"
        assert ctx.effective_date == dt.date(2026, 9, 1)
        assert ctx.source_url == "https://ex/law"
        assert "상시 30명 미만" in ctx.original_text

    def test_없는_조문은_KeyError(self):
        snapshot = parse_law_detail(load_fixture("law_detail.xml"))
        with pytest.raises(KeyError):
            snapshot.to_legal_context("제99조")


class TestChapterHeadings:
    """회귀: 법제처는 편/장/절 제목도 <조문단위>로 내려보내며 뒤따르는 조문과
    조문번호를 공유한다. 이를 조문으로 취급하면 '제1조'가 "제1장 총칙"으로 잡혀
    인용 검증(FR-021)과 LLM 컨텍스트가 오염된다.
    """

    @pytest.fixture
    def snapshot(self):
        return parse_law_detail(load_fixture("law_detail.xml"))

    def test_장_제목은_조문이_아니다(self, snapshot):
        texts = [a.original_text for a in snapshot.articles]
        assert not any(t.startswith("제5장") or t.startswith("제6장") for t in texts)

    def test_조문번호가_중복되지_않는다(self, snapshot):
        nos = [a.article_no for a in snapshot.articles]
        assert len(nos) == len(set(nos))

    def test_조문번호로_찾으면_실제_조문이_나온다(self, snapshot):
        article = snapshot.find_article("제26조")
        assert article is not None
        assert article.article_title == "고충처리위원"
        assert "고충처리위원을 두어야 한다" in article.original_text

    def test_장_제목은_chapter로_보존된다(self, snapshot):
        assert snapshot.find_article("제26조").chapter == "제5장 고충처리"

    def test_장이_바뀌면_chapter도_바뀐다(self, snapshot):
        assert snapshot.find_article("제27조의2").chapter == "제6장 보칙"

    def test_조문여부가_없으면_조문으로_취급(self):
        """구형/축약 응답 방어 — <조문여부> 태그가 없어도 조문은 유지되어야 한다."""
        xml = """<법령><기본정보><법령ID>1</법령ID><법령명_한글>테스트법</법령명_한글>
        </기본정보><조문><조문단위><조문번호>1</조문번호>
        <조문내용>제1조(목적) 이 법은 시험을 목적으로 한다.</조문내용>
        </조문단위></조문></법령>"""
        snapshot = parse_law_detail(xml)
        assert [a.article_no for a in snapshot.articles] == ["제1조"]


class TestSupplementaryLabel:
    def test_부칙은_공포번호로_구분된다(self):
        snapshot = parse_law_detail(load_fixture("law_detail.xml"))
        supp = [a for a in snapshot.articles if a.is_supplementary]
        assert supp[0].article_no == "부칙 제20114호(2026-03-10)"
