"""법률↔시행령 페어링 (ADR-025).

이 모듈의 값은 전부 홀드아웃 실측에서 나온 실패에서 역산한 것이다. 규칙 하나를
느슨하게 풀면 엉뚱한 조문이 근거로 붙고, 조이면 진짜 이행 조문을 놓친다.
경계를 테스트로 고정한다.
"""

import pytest

from app.adapters.law.decree import (
    back_references,
    build_back_reference_index,
    decree_names,
    pair_articles,
    resolves_criterion,
)
from app.adapters.law.models import LawArticle, LawSnapshot


def article(no: str, title: str, text: str, *, supplementary: bool = False) -> LawArticle:
    return LawArticle(
        article_no=no, article_title=title, original_text=text, is_supplementary=supplementary
    )


def snapshot(*articles: LawArticle) -> LawSnapshot:
    return LawSnapshot(
        law_id="005247", law_name="최저임금법 시행령",
        law_type="대통령령", articles=list(articles),
    )


class TestDecreeNames:
    def test_위임_대상에_맞는_하위법령_이름을_만든다(self) -> None:
        assert decree_names("최저임금법", ["대통령령"]) == ["최저임금법 시행령"]
        assert decree_names("최저임금법", ["부령"]) == ["최저임금법 시행규칙"]

    def test_대통령령과_부령이_함께_있으면_둘_다(self) -> None:
        assert decree_names("최저임금법", ["대통령령", "부령"]) == [
            "최저임금법 시행령",
            "최저임금법 시행규칙",
        ]

    def test_총리령도_시행규칙이라_중복되지_않는다(self) -> None:
        assert decree_names("어떤법", ["부령", "총리령"]) == ["어떤법 시행규칙"]

    def test_위임이_없으면_빈_목록(self) -> None:
        assert decree_names("최저임금법", []) == []


class TestBackReferences:
    def test_모법_참조를_뽑는다(self) -> None:
        assert back_references("제5조의2(월 환산액) 법 제6조제4항에 따라") == {"제6조"}

    def test_항_번호_뒤의_참조도_잡는다(self) -> None:
        assert back_references("제11조(주지 의무) ① 법 제11조에 따라 사용자는") == {"제11조"}

    def test_가지번호를_구분한다(self) -> None:
        assert back_references("제1조(목적) 법 제5조의2에 따른") == {"제5조의2"}

    @pytest.mark.parametrize(
        "text",
        [
            "제1조(목적) 「근로기준법」 제50조에 따른 근로시간",
            "제1조(목적) 근로기준법 제50조에 따른 근로시간",
        ],
    )
    def test_다른_법률_참조는_모법으로_보지_않는다(self, text: str) -> None:
        """'법'은 하위법령에서 모법을 가리키는 관용 표기다. 앞에 법령명이 붙으면 타법이다.

        구분하지 않으면 최저임금법 시행령에 적힌 '근로기준법 제50조'를 보고
        최저임금법 제50조에 엉뚱한 근거를 붙이게 된다.
        """
        assert back_references(text) == set()

    def test_이_법은_자기_자신이므로_제외한다(self) -> None:
        assert back_references("제1조(목적) 이 법 제3조에 따라") == set()

    def test_호_안쪽의_스쳐가는_참조는_잡지_않는다(self) -> None:
        """실제 실패 사례: 개인정보 보호법 시행령 제30조.

        '법 제31조에 따른 개인정보 보호책임자의 지정'은 제31조를 이행하는 규정이
        아니라 다른 규정을 설명하려고 제31조를 명사처럼 쓴 것이다. 이것까지
        잡았더니 무관한 조문 셋이 근거로 붙었다.
        """
        text = (
            "제30조(개인정보의 안전성 확보 조치) ① 개인정보처리자는 법 제29조에 따라 "
            "다음 각 호의 안전성 확보 조치를 해야 한다. "
            "1. 내부 관리계획의 수립ㆍ시행 및 점검 "
            "가. 개인정보취급자에 대한 관리ㆍ감독 및 교육에 관한 사항 "
            "나. 법 제31조에 따른 개인정보 보호책임자의 지정 등 개인정보 보호 조직의 구성"
        )
        refs = back_references(text)
        assert refs == {"제29조"}, "근거 절의 제29조만 남아야 한다"

    def test_basis_only를_끄면_전부_잡는다(self) -> None:
        text = (
            "제30조(안전성 확보 조치) ① 개인정보처리자는 법 제29조에 따라 한다. "
            "나. 법 제31조에 따른 개인정보 보호책임자의 지정"
        )
        assert back_references(text, basis_only=False) == {"제29조", "제31조"}


class TestResolvesCriterion:
    def test_기준을_담고_있으면_참(self) -> None:
        assert resolves_criterion("법 제11조제3항에 따른 보관기간은 다음 각 호와 같다. 1. 6개월")

    def test_별표로_넘기면_거짓(self) -> None:
        """실제 실패 사례: 산업안전보건법 시행령 제16조.

        별표는 법제처 조문 본문에 딸려 오지 않는다. '별표 3과 같다'만 주면
        모델은 기준을 못 본 채 판정하게 되고, 실측에서 150인 제조업이
        '무관'으로 나왔다. 놓치는 것은 보류보다 나쁘다.
        """
        assert not resolves_criterion(
            "① 법 제17조제1항에 따라 안전관리자를 두어야 하는 사업의 종류와 "
            "사업장의 상시근로자 수는 별표 3과 같다."
        )

    def test_따옴표_안의_정의_대상은_위임이_아니다(self) -> None:
        """이행 조문의 전형적 문장이 '대통령령으로 정하는 X란 ...'이다.

        따옴표 안을 위임으로 세면 이행 조문이 전부 미해소로 잡혀 기능이 꺼진다.
        """
        assert resolves_criterion(
            '법 제31조제8항에서 "대통령령으로 정하는 공동의 사업"이란 '
            "다음 각 호의 사업을 말한다. 1. 정책의 조사ㆍ연구"
        )

    def test_따옴표_밖의_재위임은_거짓(self) -> None:
        assert not resolves_criterion("세부 사항은 고용노동부령으로 정한다.")

    def test_빈_문자열은_거짓(self) -> None:
        assert not resolves_criterion("")


class TestPairing:
    def test_역참조로_이행_조문을_찾는다(self) -> None:
        decree = snapshot(
            article(
                "제5조의2", "월 환산액의 산정",
                "제5조의2(월 환산액의 산정) 법 제6조제4항에 따른 월 환산액은 다음과 같다",
            ),
            article(
                "제12조", "위원 위촉",
                "제12조(위원 위촉) 법 제14조제1항에 따라 위원을 위촉한다",
            ),
        )
        pairs = pair_articles("제6조", "최저임금의 효력", decree)
        assert [p.article_no for p in pairs] == ["제5조의2"]
        assert pairs[0].matched_by == "back_reference"
        assert pairs[0].law_name == "최저임금법 시행령"

    def test_조문제목이_같으면_역참조가_없어도_붙인다(self) -> None:
        decree = snapshot(
            article("제11조", "주지 의무", "제11조(주지 의무) 사용자는 게시하여야 한다")
        )
        pairs = pair_articles("제11조", "주지 의무", decree)
        assert [(p.article_no, p.matched_by) for p in pairs] == [("제11조", "article_title")]

    def test_조번호만_같은_것은_붙이지_않는다(self) -> None:
        """시행령 조번호는 모법과 독립적으로 매겨진다. 우연의 일치가 흔하다."""
        decree = snapshot(
            article("제6조", "전혀 다른 제목", "제6조(전혀 다른 제목) 아무 관련 없는 내용")
        )
        assert pair_articles("제6조", "최저임금의 효력", decree) == []

    def test_구체적인_조문이_앞에_온다(self) -> None:
        """맨 앞 조문으로 보류 해제를 결정하므로 순서가 판정을 바꾼다."""
        decree = snapshot(
            article(
                "제11조", "주지 의무",
                "제11조(주지 의무) ① 법 제11조에 따라 ② 법 제6조제4항 및 법 제7조에 따라",
            ),
            article(
                "제5조의2", "월 환산액",
                "제5조의2(월 환산액) 법 제6조제4항에 따른 월 환산액",
            ),
        )
        pairs = pair_articles("제6조", "최저임금의 효력", decree)
        assert pairs[0].article_no == "제5조의2", "참조가 적은 쪽이 더 구체적이다"

    def test_상한을_넘지_않는다(self) -> None:
        decree = snapshot(*[
            article(f"제{i}조", f"제목{i}", f"제{i}조(제목{i}) 법 제6조에 따라 정한다 {i}")
            for i in range(1, 9)
        ])
        assert len(pair_articles("제6조", None, decree, limit=3)) == 3

    def test_부칙은_제외한다(self) -> None:
        decree = snapshot(
            article("제1조", "시행일", "제1조(시행일) 법 제6조에 따라", supplementary=True),
        )
        assert pair_articles("제6조", "최저임금의 효력", decree) == []

    def test_재위임_조문은_기준_미해소로_표시된다(self) -> None:
        decree = snapshot(
            article("제16조", "안전관리자의 선임 등",
                    "제16조(안전관리자의 선임 등) ① 법 제17조제1항에 따라 두어야 하는 "
                    "사업의 종류와 상시근로자 수는 별표 3과 같다"),
        )
        pairs = pair_articles("제17조", "안전관리자", decree)
        assert len(pairs) == 1
        assert pairs[0].resolves_criterion is False


class TestIndex:
    def test_한_조문이_여러_모법_조문에_걸린다(self) -> None:
        decree = snapshot(
            article(
                "제11조", "주지 의무",
                "제11조(주지 의무) ① 법 제11조에 따라 ② 법 제7조에 따라",
            ),
        )
        index = build_back_reference_index(decree)
        assert set(index) == {"제11조", "제7조"}
