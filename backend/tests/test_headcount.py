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
        assert "충족" in e.to_prompt_block()

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
        from app.domain.outputs import TargetExtractionOutput

        reasons = deterministic_hold_reasons(self._packet(80), TargetExtractionOutput())
        assert reasons == []

    def test_인원이_미상이면_규모_보류사유_발생(self):
        from app.ai.chains.c4_mapping import deterministic_hold_reasons
        from app.domain.outputs import TargetExtractionOutput

        reasons = deterministic_hold_reasons(self._packet(None), TargetExtractionOutput())
        assert len(reasons) == 1
        assert "상시 10명 이상" in reasons[0]

    def test_LLM이_size로_분류하지_않아도_보류가_잡힌다(self):
        """정규식이 1차 방어선이므로 C3 라벨에 의존하지 않는다."""
        from app.ai.chains.c4_mapping import deterministic_hold_reasons
        from app.domain.outputs import TargetExtractionOutput

        extraction = TargetExtractionOutput(
            conditions=[
                {
                    "description": "취업규칙 작성 의무자",
                    "kind": "other",
                    "is_required": True,
                    "cited_span": "취업규칙을 작성하여야 한다",
                }
            ]
        )
        assert deterministic_hold_reasons(self._packet(None), extraction)
