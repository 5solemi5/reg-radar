"""규모 기준 판정 테스트 (AP-03).

실제 E2E에서 '80명인데 보류'가 나온 회귀를 고정한다.
"""

import pytest

from app.diff.headcount import SizeVerdict, evaluate, extract_thresholds


class TestExtraction:
    @pytest.mark.parametrize(
        "text,value,op",
        [
            ("상시 10명 이상의 근로자를 사용하는 사용자는", 10, "이상"),
            ("상시 5명 미만의 근로자를 사용하는 사업", 5, "미만"),
            ("상시근로자 수가 300명 이상인 사업장", 300, "이상"),
            ("상시근로자 1,000명 초과", 1000, "초과"),
            ("근로자 50명 이하인 경우", 50, "이하"),
        ],
    )
    def test_기준_추출(self, text, value, op):
        (t,) = extract_thresholds(text)
        assert (t.value, t.operator) == (value, op)

    def test_기준이_없으면_빈_목록(self):
        assert extract_thresholds("사업주는 안전보건교육을 실시하여야 한다.") == []

    def test_중복_기준은_한_번만(self):
        text = "상시 10명 이상의 사용자는 ... 상시 10명 이상의 사업장은 ..."
        assert len(extract_thresholds(text)) == 1

    def test_본문과_단서의_서로_다른_기준을_모두_잡는다(self):
        text = (
            "모든 사업장에는 고충처리위원을 두어야 한다. "
            "다만, 상시 30명 미만의 근로자를 사용하는 사업장은 그러하지 아니하다."
        )
        (t,) = extract_thresholds(text)
        assert (t.value, t.operator) == (30, "미만")


class TestEvaluate:
    TEXT = "상시 10명 이상의 근로자를 사용하는 사용자는 취업규칙을 작성하여야 한다."

    def test_충족(self):
        e = evaluate(self.TEXT, 80)
        assert e.verdict is SizeVerdict.MEETS
        assert "80명은 해당함" in e.to_prompt_block()

    def test_미충족(self):
        assert evaluate(self.TEXT, 4).verdict is SizeVerdict.BELOW

    def test_경계값은_이상에_포함(self):
        assert evaluate(self.TEXT, 10).verdict is SizeVerdict.MEETS
        assert evaluate(self.TEXT, 9).verdict is SizeVerdict.BELOW

    def test_인원_미상은_UNKNOWN(self):
        e = evaluate(self.TEXT, None)
        assert e.verdict is SizeVerdict.UNKNOWN
        assert "미상" in e.to_prompt_block()

    def test_기준_없으면_NO_CONDITION(self):
        assert evaluate("사업주는 교육을 실시한다.", 80).verdict is SizeVerdict.NO_CONDITION

    def test_프롬프트_블록은_판정회피를_차단하는_문구를_포함(self):
        assert "판정을 회피하지 마십시오" in evaluate(self.TEXT, 80).to_prompt_block()


class TestHoldReasonIntegration:
    """deterministic_hold_reasons가 코드 계산에 근거하는지."""

    def _packet(self, count):
        import datetime as dt

        from app.domain.context import ChangeContext, ContextPacket, LegalContext, UserContext
        from app.domain.enums import ChangeType, CompanySize

        return ContextPacket(
            user=UserContext(
                job="HR", industry="IT", company_size=CompanySize.MEDIUM, employee_count=count
            ),
            law=LegalContext(
                law_id="1", law_name="근로기준법", article_no="제93조",
                effective_date=dt.date(2026, 8, 20),
                original_text=TestEvaluate.TEXT,
            ),
            change=ChangeContext(change_type=ChangeType.AMENDED),
        )

    def test_인원이_있으면_규모_보류사유_없음(self):
        from app.ai.chains.c4_mapping import deterministic_hold_reasons

        assert deterministic_hold_reasons(self._packet(80)) == []

    def test_인원이_미상이면_규모_보류사유_발생(self):
        from app.ai.chains.c4_mapping import deterministic_hold_reasons

        reasons = deterministic_hold_reasons(self._packet(None))
        assert len(reasons) == 1
        assert "상시 10명 이상" in reasons[0]

    def test_규모기준이_없는_조문은_인원_미상이어도_보류하지_않는다(self):
        """실측 회귀(E06): 근로기준법 제54조(휴게)는 규모 조건이 없는데
        '상시근로자 수 미상'을 이유로 보류하는 오답이 나왔다.
        원문에 기준이 없으면 LLM이 size 조건을 만들어내도 보류하지 않는다.
        """
        import datetime as dt

        from app.ai.chains.c4_mapping import deterministic_hold_reasons
        from app.domain.context import ChangeContext, ContextPacket, LegalContext, UserContext
        from app.domain.enums import ChangeType, CompanySize

        packet = ContextPacket(
            user=UserContext(
                job="운영팀장", industry="제조",
                company_size=CompanySize.MEDIUM, employee_count=None,
            ),
            law=LegalContext(
                law_id="1", law_name="근로기준법", article_no="제54조",
                effective_date=dt.date(2026, 8, 20),
                original_text=(
                    "제54조(휴게) ① 사용자는 근로시간이 4시간인 경우에는 30분 이상, "
                    "8시간인 경우에는 1시간 이상의 휴게시간을 근로시간 도중에 주어야 한다."
                ),
            ),
            change=ChangeContext(change_type=ChangeType.NEW),
        )
        assert deterministic_hold_reasons(packet) == []


class TestExclusionClause:
    """같은 '상시 30명'이라도 적용 조건이냐 배제 조건이냐에 따라 결론이 정반대다.

    구분하지 않으면 80명 회사가 "상시 30명 미만 → 미충족"을 보고 '적용 안 된다'로
    읽는다. 노사협의회는 30명 이상이면 설치해야 하므로 정확히 거꾸로다. 게다가
    프롬프트가 "이 값을 의심하지 말라"고 못까지 박아 모델이 되돌릴 수도 없다.
    """

    EXCLUSION = (
        "협의회는 사업장 단위로 설치하여야 한다. "
        "다만, 상시 30명 미만의 근로자를 사용하는 사업이나 사업장은 그러하지 아니하다."
    )
    CONDITION = "상시 10명 이상의 근로자를 사용하는 사용자는 취업규칙을 작성하여야 한다."

    def test_배제_단서를_표시한다(self):
        (threshold,) = extract_thresholds(self.EXCLUSION)
        assert threshold.in_exclusion_clause is True

    def test_적용_조건은_표시하지_않는다(self):
        (threshold,) = extract_thresholds(self.CONDITION)
        assert threshold.in_exclusion_clause is False

    def test_배제_단서는_프롬프트에_명시된다(self):
        block = evaluate(self.EXCLUSION, 80).to_prompt_block()
        assert "[적용 배제]" in block
        assert "80명은 해당하지 않음" in block
        assert "해당하지 않으면 배제되지 않습니다" in block

    def test_적용_조건에는_배제_안내가_없다(self):
        assert "[적용 배제]" not in evaluate(self.CONDITION, 80).to_prompt_block()

    def test_아니한다_종결형을_놓치지_않는다(self):
        """'아니하'로 찾으면 법조문에 가장 흔한 '아니한다'를 정확히 비껴간다.

        `정하`가 `정한다`에 매치되지 않던 것과 같은 함정이다. 세 번째로 밟았으므로
        활용형은 app/diff/korean.py 한 곳에 모아 두었다.
        """
        text = (
            "상시 근로자가 5명 미만인 사업 또는 사업장의 사업주에게는 "
            "이 장의 규정을 적용하지 아니한다."
        )
        (threshold,) = extract_thresholds(text)
        assert threshold.in_exclusion_clause is True


class TestSubjectParticle:
    """조사(가/이/는/은)를 빼먹으면 규모 기준을 통째로 놓친다."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("상시 10명 이상", "상시 10명 이상"),
            ("상시근로자 수가 300명 미만", "상시근로자 수가 300명 미만"),
            ("근로자 5명 이상", "근로자 5명 이상"),
            ("상시 근로자가 5명 미만", "상시 근로자가 5명 미만"),
            ("상시 근로자 수가 50명 이상", "상시 근로자 수가 50명 이상"),
        ],
    )
    def test_표현_변형을_모두_잡는다(self, text: str, expected: str):
        thresholds = extract_thresholds(text)
        assert [t.raw for t in thresholds] == [expected]
