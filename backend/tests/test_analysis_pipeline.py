"""C3~C6 파이프라인 통합 테스트 — LLM은 Fake로 대체 (UC-03, UC-04)."""

import datetime as dt

from app.ai.chains.base import ChainRunner
from app.ai.chains.c4_mapping import unverifiable_target_reason
from app.ai.llm import LlmGateway
from app.domain.context import ChangeContext, ContextPacket, LegalContext, UserContext
from app.domain.enums import (
    ActionGrade,
    Applicability,
    ChangeType,
    CompanySize,
    ResultStatus,
)
from app.domain.outputs import (
    ApplicabilityOutput,
    ImpactOutput,
    TargetExtractionOutput,
    TargetGroupBasis,
)
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
    target_group="사용자",
    target_group_basis=TargetGroupBasis.PROFILE_STATES,
    profile_evidence="- 업종: IT 서비스",
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
            target_group="유해화학물질 영업자",
            # 프로필이 '대상이 아님'을 말해 준다 → 무관 확정이 근거를 갖는다.
            target_group_basis=TargetGroupBasis.PROFILE_EXCLUDES,
            profile_evidence="- 업종: IT 서비스",
            reason="이 조문은 해당 업종과 무관합니다.",
            confidence=0.8,
        )
        packet = make_packet(employee_count=None, delegation=["대통령령"])
        out = await analyze_article(runner_for(applicability=not_app), packet)
        assert out.result.applicability is Applicability.NOT_APPLICABLE

    async def test_무관이면_C5를_호출하지_않는다(self):
        not_app = ApplicabilityOutput(
            applicability=Applicability.NOT_APPLICABLE,
            target_group="유해화학물질 영업자",
            target_group_basis=TargetGroupBasis.PROFILE_EXCLUDES,
            profile_evidence="- 업종: IT 서비스",
            reason="무관합니다.",
            confidence=0.8,
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


class TestTargetGroupPolicy:
    """대상 집단 해당 여부를 프로필로 알 수 없으면 확정하지 않는다 (AP-03).

    규모 기준은 코드가 계산해 강제했지만 '이 회사가 도급인인가' 같은 지위 미지수는
    LLM에 맡겨져 있었다. 프롬프트가 "보류를 남용하지 마십시오"로 강하게 눌러 놓아
    모르는 것도 업종만 보고 결정했고, holdout_v2에서 보류 재현율 40%로 나타났다.
    놓친 3건이 전부 이 유형이었다.
    """

    @staticmethod
    def _out(
        basis: TargetGroupBasis,
        applicability: Applicability,
        evidence: str | None = "- 업종: IT 서비스",
    ) -> ApplicabilityOutput:
        return ApplicabilityOutput(
            applicability=applicability,
            target_group="도급인",
            target_group_basis=basis,
            profile_evidence=None if basis is TargetGroupBasis.PROFILE_SILENT else evidence,
            reason="판정 근거",
            missing_context=["상시근로자 수"] if applicability is Applicability.HOLD else [],
            cited_spans=["고충처리위원을 두어야 한다"]
            if applicability is Applicability.APPLICABLE
            else [],
            confidence=0.8,
        )

    async def test_판단_불가면_무관도_보류로_강등한다(self):
        """대상인지 모르는데 '무관'이라고 말하는 것은 근거 없는 확정이다.

        위임·규모 사유는 무관을 강등하지 않는다. 이 사유만 예외인 이유는, 무관이라는
        판단 **자체**가 대상 집단 판단에 기대고 있는데 그 근거가 없기 때문이다.
        """
        out = await analyze_article(
            runner_for(
                applicability=self._out(
                    TargetGroupBasis.PROFILE_SILENT, Applicability.NOT_APPLICABLE
                )
            ),
            make_packet(employee_count=80),
        )
        assert out.result.applicability is Applicability.HOLD
        assert any("도급인" in m for m in out.result.ai_interpretation.missing_context)

    async def test_판단_불가면_해당도_보류로_강등한다(self):
        out = await analyze_article(
            runner_for(
                applicability=self._out(
                    TargetGroupBasis.PROFILE_SILENT, Applicability.APPLICABLE
                )
            ),
            make_packet(employee_count=80),
        )
        assert out.result.applicability is Applicability.HOLD

    async def test_프로필이_대상임을_말해주면_그대로_확정한다(self):
        out = await analyze_article(
            runner_for(
                applicability=self._out(
                    TargetGroupBasis.PROFILE_STATES, Applicability.APPLICABLE
                )
            ),
            make_packet(employee_count=80),
        )
        assert out.result.applicability is Applicability.APPLICABLE

    async def test_프로필이_대상_아님을_말해주면_무관을_유지한다(self):
        """이걸 강등하면 대시보드가 보류로 가득 찬다. 원래의 70% 과보류로 돌아간다."""
        out = await analyze_article(
            runner_for(
                applicability=self._out(
                    TargetGroupBasis.PROFILE_EXCLUDES, Applicability.NOT_APPLICABLE
                )
            ),
            make_packet(employee_count=80),
        )
        assert out.result.applicability is Applicability.NOT_APPLICABLE

    def test_강등_사유가_무엇을_물어야_하는지_말해준다(self):
        reason = unverifiable_target_reason(
            self._out(TargetGroupBasis.PROFILE_SILENT, Applicability.NOT_APPLICABLE)
        )
        assert reason is not None
        assert "도급인" in reason

    def test_프로필에_있는_근거로_확정하면_사유가_없다(self):
        packet = make_packet(employee_count=80)
        line = packet.user.to_prompt_block().splitlines()[1]  # "- 업종: ..."
        for basis in (TargetGroupBasis.PROFILE_STATES, TargetGroupBasis.PROFILE_EXCLUDES):
            out = self._out(basis, Applicability.APPLICABLE, evidence=line)
            assert unverifiable_target_reason(out, packet) is None

    def test_근거를_아예_빼먹으면_보류로_떨어진다(self):
        """스키마 예외로 막지 않는 이유. 여기서 던지면 분석 전체가 죽는다."""
        packet = make_packet(employee_count=80)
        out = self._out(
            TargetGroupBasis.PROFILE_EXCLUDES,
            Applicability.NOT_APPLICABLE,
            evidence=None,
        )
        assert unverifiable_target_reason(out, packet) is not None

    def test_프로필에_없는_근거는_확정으로_인정하지_않는다(self):
        """스키마는 값을 요구할 뿐이다. 그 값이 실제 프로필에 있는지는 코드가 본다.

        요구만 했을 때 모델은 "IT 서비스라서 정보통신서비스 제공자가 아니다" 같은
        그럴듯한 문장을 지어냈다. holdout_v3 오답 6건이 전부 이런 근거 없는 무관
        확정이었다.
        """
        packet = make_packet(employee_count=80)
        out = self._out(
            TargetGroupBasis.PROFILE_EXCLUDES,
            Applicability.NOT_APPLICABLE,
            evidence="- 업종: 존재하지 않는 업종",
        )
        assert unverifiable_target_reason(out, packet) is not None
