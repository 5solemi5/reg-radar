"""C6 Validator 테스트 (FR-020~022, Q2, Q6, ER-004)."""

import datetime as dt

import pytest

from app.domain.context import ChangeContext, ContextPacket, LegalContext, RagContext, UserContext
from app.domain.enums import Applicability, ChangeType, CompanySize, DocType, ResultStatus
from app.domain.outputs import ApplicabilityOutput, ChecklistItem, ImpactOutput, TargetGroupBasis
from app.validator.core import validate
from app.validator.rules import verify_citations

ORIGINAL = (
    "제26조(고충처리위원)\n"
    "① 모든 사업 또는 사업장에는 근로자의 고충을 청취하고 이를 처리하기 위하여 "
    "고충처리위원을 두어야 한다. 다만, 상시 30명 미만의 근로자를 사용하는 사업이나 "
    "사업장은 그러하지 아니하다.\n"
    "② 고충처리위원의 선임과 운영에 필요한 사항은 대통령령으로 정한다."
)


@pytest.fixture
def packet():
    return ContextPacket(
        user=UserContext(
            job="HR 담당자",
            industry="IT 서비스",
            company_size=CompanySize.MEDIUM,
            employee_count=80,
        ),
        law=LegalContext(
            law_id="001766",
            law_name="근로자참여 및 협력증진에 관한 법률",
            article_no="제26조",
            article_title="고충처리위원",
            effective_date=dt.date(2026, 9, 1),
            promulgation_date=dt.date(2026, 3, 10),
            ministry="고용노동부",
            original_text=ORIGINAL,
        ),
        change=ChangeContext(
            change_type=ChangeType.AMENDED,
            additions=["② 고충처리위원의 선임과 운영에 필요한 사항은 대통령령으로 정한다."],
            delegation_targets=["대통령령"],
        ),
        rag=[],
    )


def applicable(**kw) -> ApplicabilityOutput:
    base = dict(
        applicability=Applicability.APPLICABLE,
        target_group="사용자",
        target_group_basis=TargetGroupBasis.PROFILE_STATES,
        profile_evidence="- 업종: IT 서비스",
        reason="상시 30명 이상을 사용하는 사업장이므로 고충처리위원을 두어야 합니다.",
        cited_spans=["고충처리위원을 두어야 한다"],
        confidence=0.9,
    )
    return ApplicabilityOutput(**{**base, **kw})


def impact(**kw) -> ImpactOutput:
    base = dict(
        summary="고충처리위원 선임 여부를 점검해야 합니다.",
        affected_work=["취업규칙"],
        action_grade="ACTION",
        action_grade_reason="선임 의무가 있습니다.",
        checklist=[ChecklistItem(title="고충처리위원 선임 현황 확인")],
        cited_spans=["고충처리위원을 두어야 한다"],
    )
    return ImpactOutput(**{**base, **kw})


class TestCitationVerification:
    def test_원문에_있는_인용은_통과(self):
        ok, dropped = verify_citations(["고충처리위원을 두어야 한다"], ORIGINAL)
        assert ok and not dropped

    def test_줄바꿈_공백_차이는_흡수(self):
        ok, _ = verify_citations(["고충처리위원을   두어야\n한다"], ORIGINAL)
        assert ok

    def test_지어낸_인용은_탈락(self):
        ok, dropped = verify_citations(["상시 10명 이상의 근로자"], ORIGINAL)
        assert not ok and dropped == ["상시 10명 이상의 근로자"]

    def test_요약된_인용도_탈락(self):
        """모델이 원문을 '정리'해서 인용하는 흔한 실패 모드."""
        ok, dropped = verify_citations(["고충처리위원을 두어야 함"], ORIGINAL)
        assert not ok and dropped

    def test_검증실패_인용은_결과에서_제거된다(self, packet):
        out = validate(packet, applicable(cited_spans=["고충처리위원을 두어야 한다", "가짜 문구"]))
        assert out.applicability.cited_spans == ["고충처리위원을 두어야 한다"]
        assert out.report.dropped_spans == ["가짜 문구"]


class TestFabricationBlocking:
    """Q6. 금지 필드 유출 0건 — 자유 서술에 숨어든 사실 위조를 잡는다."""

    def test_원문에_없는_조문번호_생성시_REJECT(self, packet):
        out = validate(packet, applicable(reason="제99조에 따라 해당합니다."))
        assert out.status is ResultStatus.REJECTED
        assert not out.accepted
        assert any("제99조" in f for f in out.report.failures)

    def test_분석대상_조문_자신은_허용(self, packet):
        out = validate(packet, applicable(reason="제26조는 고충처리위원을 두도록 합니다."))
        assert out.status is ResultStatus.VALIDATED

    def test_원문이_인용한_타조문은_허용(self):
        p = ContextPacket(
            user=UserContext(job="HR", industry="IT", company_size=CompanySize.SMALL),
            law=LegalContext(
                law_id="1", law_name="테스트법", article_no="제3조",
                original_text="제3조(적용) 제10조에 따른 사업장에 적용한다.",
            ),
            change=ChangeContext(change_type=ChangeType.NEW),
        )
        out = validate(
            p,
            ApplicabilityOutput(
                applicability=Applicability.APPLICABLE,
                target_group="사용자",
                target_group_basis=TargetGroupBasis.PROFILE_STATES,
                profile_evidence="- 업종: IT 서비스",
                reason="제10조에 따른 사업장에 해당합니다.",
                cited_spans=["제10조에 따른 사업장에 적용한다"],
                confidence=0.8,
            ),
        )
        assert out.status is ResultStatus.VALIDATED

    def test_시행일_위조시_REJECT(self, packet):
        out = validate(packet, applicable(reason="2027년 1월 1일부터 시행됩니다."))
        assert out.status is ResultStatus.REJECTED
        assert any("2027-01-01" in f for f in out.report.failures)

    def test_공식_시행일_언급은_허용(self, packet):
        out = validate(packet, applicable(reason="2026년 9월 1일부터 시행됩니다."))
        assert out.status is ResultStatus.VALIDATED

    def test_참고자료가_없는데_인용하면_REJECT(self, packet):
        out = validate(packet, applicable(reason="[R1] 고용노동부 가이드에 따르면 해당합니다."))
        assert out.status is ResultStatus.REJECTED
        assert any("[R1]" in f for f in out.report.failures)

    def test_범위내_참고자료_인용은_허용(self, packet):
        with_rag = packet.model_copy(
            update={
                "rag": [
                    RagContext(
                        doc_id="d1", source="https://moel.go.kr/x", agency="고용노동부",
                        doc_type=DocType.GUIDE, snippet="고충처리위원 운영 안내",
                    )
                ]
            }
        )
        out = validate(with_rag, applicable(reason="[R1] 가이드를 참고하면 해당합니다."))
        assert out.status is ResultStatus.VALIDATED

    def test_영향_서술의_위조도_잡는다(self, packet):
        bad = impact(summary="제77조 개정에 따라 조치가 필요합니다.")
        out = validate(packet, applicable(), bad)
        assert out.status is ResultStatus.REJECTED


class TestSubstantiation:
    """Q2. 근거 없는 '해당' 확정이 가장 위험한 오탐이다."""

    def test_인용이_하나도_없는_APPLICABLE은_REJECT(self, packet):
        out = validate(packet, applicable(cited_spans=[]))
        assert out.status is ResultStatus.REJECTED
        assert any("인용 없이" in f for f in out.report.failures)

    def test_인용이_전부_탈락해도_REJECT(self, packet):
        out = validate(packet, applicable(cited_spans=["없는 문구"]))
        assert out.status is ResultStatus.REJECTED

    def test_NOT_APPLICABLE은_인용_없어도_통과(self, packet):
        out = validate(
            packet,
            ApplicabilityOutput(
                applicability=Applicability.NOT_APPLICABLE,
                target_group="사용자",
                target_group_basis=TargetGroupBasis.PROFILE_STATES,
                profile_evidence="- 업종: IT 서비스",
                reason="이 조문은 사업장 규모와 무관한 내용입니다.",
                cited_spans=[],
                confidence=0.7,
            ),
        )
        assert out.status is ResultStatus.VALIDATED

    def test_HOLD도_인용_없이_통과(self, packet):
        out = validate(
            packet,
            ApplicabilityOutput(
                applicability=Applicability.HOLD,
                target_group="사용자",
                target_group_basis=TargetGroupBasis.PROFILE_STATES,
                profile_evidence="- 업종: IT 서비스",
                reason="구체 기준이 대통령령에 위임되어 있습니다.",
                missing_context=["대통령령이 정하는 선임 기준"],
                cited_spans=[],
                confidence=0.5,
            ),
        )
        assert out.status is ResultStatus.HOLD
        assert out.accepted


class TestReport:
    def test_정상결과의_체크목록(self, packet):
        out = validate(packet, applicable(), impact())
        assert out.report.passed
        assert all(out.report.checks.values())
        assert out.report.failures == []

    def test_HOLD는_downgraded_플래그(self, packet):
        out = validate(
            packet,
            ApplicabilityOutput(
                applicability=Applicability.HOLD,
                target_group="사용자",
                target_group_basis=TargetGroupBasis.PROFILE_STATES,
                profile_evidence="- 업종: IT 서비스",
                reason="정보 부족",
                missing_context=["상시근로자 수"],
                confidence=0.4,
            ),
        )
        assert out.report.downgraded_to_hold
