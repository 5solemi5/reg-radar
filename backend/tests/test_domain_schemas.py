"""도메인 스키마 불변식 테스트 (FR-020, BR-003, BR-007, NFR-004).

이 테스트는 '모델이 사실을 지어낼 자리 자체가 없다'는 구조적 보장을 고정한다.
스키마에 공식 사실 필드를 추가하는 순간 여기서 깨져야 한다.
"""

import pytest
from pydantic import ValidationError

from app.domain.enums import ActionGrade, Applicability
from app.domain.outputs import (
    FORBIDDEN_FACT_FIELDS,
    ApplicabilityOutput,
    ImpactOutput,
    TargetExtractionOutput,
    assert_no_forbidden_fields,
)

LLM_OUTPUT_SCHEMAS = [TargetExtractionOutput, ApplicabilityOutput, ImpactOutput]


class TestForbiddenFields:
    @pytest.mark.parametrize("schema", LLM_OUTPUT_SCHEMAS, ids=lambda s: s.__name__)
    def test_공식_사실_필드가_없다(self, schema):
        assert_no_forbidden_fields(schema)

    @pytest.mark.parametrize("schema", LLM_OUTPUT_SCHEMAS, ids=lambda s: s.__name__)
    def test_모르는_필드는_거부된다(self, schema):
        """extra='forbid' — 모델이 law_name을 끼워넣어도 파싱 단계에서 막힌다."""
        with pytest.raises(ValidationError):
            schema.model_validate({"law_name": "근로기준법"})

    def test_가드가_위반을_실제로_잡는다(self):
        from pydantic import BaseModel

        class Leaky(BaseModel):
            law_name: str

        with pytest.raises(AssertionError, match="law_name"):
            assert_no_forbidden_fields(Leaky)

    def test_금지필드_목록에_핵심_사실값이_포함(self):
        assert {"law_name", "article_no", "effective_date", "original_text"} <= (
            FORBIDDEN_FACT_FIELDS
        )


class TestHoldRule:
    """BR-003. 불확실하면 HOLD, 그리고 HOLD는 이유를 말해야 한다."""

    def test_HOLD는_missing_context가_필수(self):
        with pytest.raises(ValidationError, match="missing_context"):
            ApplicabilityOutput(
                applicability=Applicability.HOLD, reason="규모 기준 불명", confidence=0.4
            )

    def test_HOLD에_missing_context가_있으면_통과(self):
        out = ApplicabilityOutput(
            applicability=Applicability.HOLD,
            reason="상시근로자 수를 알 수 없음",
            missing_context=["상시근로자 수"],
            confidence=0.4,
        )
        assert out.applicability is Applicability.HOLD

    def test_APPLICABLE은_missing_context_없이_가능(self):
        out = ApplicabilityOutput(
            applicability=Applicability.APPLICABLE, reason="업종 일치", confidence=0.9
        )
        assert out.missing_context == []

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_confidence_범위(self, bad):
        with pytest.raises(ValidationError):
            ApplicabilityOutput(
                applicability=Applicability.NOT_APPLICABLE, reason="x", confidence=bad
            )


class TestAxisSeparation:
    """BR-007. 적용 판정과 행동 등급은 서로 다른 축이다."""

    def test_두_enum의_값이_겹치지_않는다(self):
        assert not ({e.value for e in Applicability} & {e.value for e in ActionGrade})

    def test_판정_스키마에_행동등급이_없다(self):
        assert "action_grade" not in ApplicabilityOutput.model_fields

    def test_영향_스키마에_적용판정이_없다(self):
        assert "applicability" not in ImpactOutput.model_fields


class TestCitationShape:
    def test_추출_결과에서_인용구절을_모을_수_있다(self):
        out = TargetExtractionOutput.model_validate(
            {
                "conditions": [
                    {
                        "description": "상시 30명 이상 근로자를 사용하는 사업장",
                        "kind": "size",
                        "is_required": True,
                        "cited_span": "상시 30명 미만의 근로자를 사용하는 사업",
                    }
                ]
            }
        )
        assert out.cited_spans == ["상시 30명 미만의 근로자를 사용하는 사업"]
