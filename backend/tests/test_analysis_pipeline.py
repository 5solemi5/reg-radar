"""C3~C6 파이프라인 통합 테스트 — LLM은 Fake로 대체 (UC-03, UC-04)."""

import datetime as dt

from app.ai.chains.base import ChainRunner
from app.ai.llm import LlmGateway
from app.domain.context import ChangeContext, ContextPacket, LegalContext, UserContext
from app.domain.enums import (
    ActionGrade,
    Applicability,
    ChangeType,
    CompanySize,
    ResultStatus,
)
from app.domain.outputs import ApplicabilityOutput, ImpactOutput, TargetExtractionOutput
from app.services.analysis_service import analyze_article

ORIGINAL = (
    "제26조(고충처리위원)\n"
    "① 모든 사업 또는 사업장에는 근로자의 고충을 청취하고 이를 처리하기 위하여 "
    "고충처리위원을 두어야 한다. 다만, 상시 30명 미만의 근로자를 사용하는 사업이나 "
    "사업장은 그러하지 아니하다."
)


class FakeChainRunner(ChainRunner):
    """스키마별로 미리 정한 응답을 돌려준다."""

    def __init__(self, responses: dict[type, object]):
        super().__init__(llm=LlmGateway.__new__(LlmGateway))
        self._responses = responses

    async def invoke(self, *, chain, prompt, schema):
        self.last_prompt = prompt
        if schema not in self._responses:
            raise AssertionError(f"{schema.__name__} 응답이 준비되지 않았습니다.")
        return self._responses[schema]

    @property
    def llm(self):
        class _L:
            model_name = "fake-model"
        return _L()

    @llm.setter
    def llm(self, value):
        pass


def make_packet(*, employee_count: int | None, delegation: list[str] | None = None):
    return ContextPacket(
        user=UserContext(
            job="HR 담당자",
            industry="IT 서비스",
            company_size=CompanySize.MEDIUM,
            employee_count=employee_count,
        ),
        law=LegalContext(
            law_id="001766",
            law_name="근로자참여 및 협력증진에 관한 법률",
            article_no="제26조",
            article_title="고충처리위원",
            effective_date=dt.date(2026, 9, 1),
            ministry="고용노동부",
            original_text=ORIGINAL,
        ),
        change=ChangeContext(
            change_type=ChangeType.AMENDED,
            additions=["고충처리위원을 두어야 한다"],
            delegation_targets=delegation or [],
        ),
    )


SIZE_EXTRACTION = TargetExtractionOutput(
    conditions=[
        {
            "description": "상시 30명 이상 근로자를 사용하는 사업장",
            "kind": "size",
            "is_required": True,
            "cited_span": "상시 30명 미만의 근로자를 사용하는 사업",
        }
    ]
)

APPLICABLE_OUT = ApplicabilityOutput(
    applicability=Applicability.APPLICABLE,
    reason="상시 80명을 사용하므로 고충처리위원을 두어야 합니다.",
    matched_conditions=["상시 30명 이상"],
    cited_spans=["고충처리위원을 두어야 한다"],
    confidence=0.9,
)

IMPACT_OUT = ImpactOutput(
    summary="고충처리위원 선임 현황을 점검해야 합니다.",
    affected_work=["취업규칙", "고충처리 절차"],
    action_grade=ActionGrade.ACTION,
    action_grade_reason="선임 의무가 있습니다.",
    checklist=[{"title": "고충처리위원 선임 여부 확인"}],
    cited_spans=["고충처리위원을 두어야 한다"],
)


def runner_for(extraction=SIZE_EXTRACTION, applicability=APPLICABLE_OUT, impact=IMPACT_OUT):
    return FakeChainRunner(
        {
            TargetExtractionOutput: extraction,
            ApplicabilityOutput: applicability,
            ImpactOutput: impact,
        }
    )


class TestHappyPath:
    async def test_해당_판정이_행동등급까지_간다(self):
        out = await analyze_article(runner_for(), make_packet(employee_count=80))
        r = out.result
        assert r.status is ResultStatus.VALIDATED
        assert r.applicability is Applicability.APPLICABLE
        assert r.action_grade is ActionGrade.ACTION
        assert r.is_displayable

    async def test_법적근거는_snapshot에서만_온다(self):
        out = await analyze_article(runner_for(), make_packet(employee_count=80))
        ev = out.result.legal_evidence
        assert ev.law_name == "근로자참여 및 협력증진에 관한 법률"
        assert ev.article_no == "제26조"
        assert ev.effective_date == dt.date(2026, 9, 1)
        assert ev.quoted_spans == ["고충처리위원을 두어야 한다"]

    async def test_AI해석에는_사실필드가_없다(self):
        out = await analyze_article(runner_for(), make_packet(employee_count=80))
        fields = set(type(out.result.ai_interpretation).model_fields)
        assert not ({"law_name", "article_no", "effective_date"} & fields)


class TestDeterministicHoldPolicy:
    """코드가 LLM 판정을 덮어쓰는 지점 — 기획서 §2의 20% 오탐 대응."""

    async def test_규모조건이_있는데_인원_미상이면_HOLD로_강등(self):
        out = await analyze_article(runner_for(), make_packet(employee_count=None))
        r = out.result
        assert r.applicability is Applicability.HOLD
        assert r.status is ResultStatus.HOLD
        assert any("상시근로자 수" in m for m in r.ai_interpretation.missing_context)

    async def test_HOLD에는_행동등급을_부여하지_않는다(self):
        out = await analyze_article(runner_for(), make_packet(employee_count=None))
        assert out.result.action_grade is None

    async def test_하위법령_위임이_있으면_HOLD로_강등(self):
        packet = make_packet(employee_count=80, delegation=["대통령령"])
        out = await analyze_article(runner_for(), packet)
        assert out.result.applicability is Applicability.HOLD
        assert any("대통령령" in m for m in out.result.ai_interpretation.missing_context)

    async def test_무관은_강등하지_않는다(self):
        """무관까지 HOLD로 만들면 대시보드가 보류로 가득 찬다."""
        not_app = ApplicabilityOutput(
            applicability=Applicability.NOT_APPLICABLE,
            reason="이 조문은 해당 업종과 무관합니다.",
            confidence=0.8,
        )
        packet = make_packet(employee_count=None, delegation=["대통령령"])
        out = await analyze_article(runner_for(applicability=not_app), packet)
        assert out.result.applicability is Applicability.NOT_APPLICABLE

    async def test_무관이면_C5를_호출하지_않는다(self):
        not_app = ApplicabilityOutput(
            applicability=Applicability.NOT_APPLICABLE, reason="무관합니다.", confidence=0.8
        )
        runner = FakeChainRunner(
            {TargetExtractionOutput: SIZE_EXTRACTION, ApplicabilityOutput: not_app}
        )
        out = await analyze_article(runner, make_packet(employee_count=80))
        assert out.result.ai_interpretation.impact_summary is None


class TestValidationBlocking:
    async def test_위조_조문번호가_있으면_REJECTED(self):
        bad = APPLICABLE_OUT.model_copy(update={"reason": "제99조에 따라 해당합니다."})
        out = await analyze_article(runner_for(applicability=bad), make_packet(employee_count=80))
        assert out.result.status is ResultStatus.REJECTED
        assert not out.result.is_displayable
        assert out.result.action_grade is None

    async def test_검증실패_인용은_결과에서_제거(self):
        bad = APPLICABLE_OUT.model_copy(
            update={"cited_spans": ["고충처리위원을 두어야 한다", "지어낸 문구"]}
        )
        out = await analyze_article(runner_for(applicability=bad), make_packet(employee_count=80))
        assert out.result.legal_evidence.quoted_spans == ["고충처리위원을 두어야 한다"]
        assert out.result.validation.dropped_spans == ["지어낸 문구"]


class TestContextIsolation:
    async def test_참고자료가_없으면_프롬프트에_명시된다(self):
        runner = runner_for()
        await analyze_article(runner, make_packet(employee_count=80))
        assert "참고자료를 지어내지 마십시오" in runner.last_prompt
