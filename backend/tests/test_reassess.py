"""보류 재판정 테스트 (FR-008, BR-008).

핵심은 두 가지다.
  1. 기존 결과를 덮어쓰지 않고 이력으로 연결한다 (BR-008).
  2. 분석 당시 법령 근거로 재판정한다 (AP-07, BR-006).
"""

import datetime as dt

import pytest

from app.adapters.law.models import LawArticle, LawSnapshot
from app.domain.entities import Analysis, Profile
from app.domain.enums import ActionGrade, Applicability, CompanySize, ResultStatus
from app.repositories.memory import (
    InMemoryAnalysisRepository,
    InMemoryResultRepository,
    InMemoryRevisionRepository,
    InMemorySnapshotRepository,
    InMemoryStore,
)
from app.services.reassess_service import (
    NotHoldError,
    ReassessError,
    ReassessInput,
    ReassessService,
    SnapshotMissingError,
    apply_overrides,
)
from tests.conftest import make_result

ARTICLE_TEXT = (
    "제93조(취업규칙의 작성ㆍ신고) 상시 10명 이상의 근로자를 사용하는 사용자는 "
    "취업규칙을 작성하여 고용노동부장관에게 신고하여야 한다."
)


def a_profile(employee_count: int | None = None) -> Profile:
    return Profile(
        user_id="u1",
        job="HR 담당자",
        industry="IT 서비스",
        company_size=CompanySize.MEDIUM,
        employee_count=employee_count,
        interests=["노동·인사"],
    )


def a_snapshot() -> LawSnapshot:
    return LawSnapshot(
        law_id="001872",
        law_name="근로기준법",
        ministry="고용노동부",
        effective_date=dt.date(2026, 8, 20),
        articles=[
            LawArticle(
                article_no="제93조",
                article_title="취업규칙의 작성ㆍ신고",
                effective_date=dt.date(2026, 8, 20),
                original_text=ARTICLE_TEXT,
            )
        ],
    )


class FakeAnalyzer:
    """LLM 대신 결정적 판정을 돌려준다. 인원이 있으면 해당으로 바뀐다."""

    def __init__(self, store, analysis_id):
        self.store = store
        self.analysis_id = analysis_id
        self.calls: list = []

    async def __call__(self, runner, packet, *, analysis_id=None, trace_id=None):
        from app.services.analysis_service import AnalysisOutcome

        self.calls.append(packet)
        count = packet.user.employee_count
        applicable = count is not None and count >= 10

        result = make_result(
            analysis_id=analysis_id or self.analysis_id,
            applicability=(
                Applicability.APPLICABLE if applicable else Applicability.HOLD
            ),
            action_grade=ActionGrade.ACTION if applicable else None,
            status=ResultStatus.VALIDATED if applicable else ResultStatus.HOLD,
        )
        if not applicable:
            result = result.model_copy(
                update={
                    "ai_interpretation": result.ai_interpretation.model_copy(
                        update={"missing_context": ["상시근로자 수"]}
                    )
                }
            )
        return AnalysisOutcome(result=result, traces=[], total_latency_ms=10)


@pytest.fixture
def setup(monkeypatch):
    """보류 결과 하나가 저장된 상태를 만든다."""
    store = InMemoryStore()

    async def prepare():
        analysis = await InMemoryAnalysisRepository(store).create(
            Analysis(user_id="u1")
        )
        original = make_result(
            analysis_id=analysis.analysis_id,
            applicability=Applicability.HOLD,
            action_grade=None,
            status=ResultStatus.HOLD,
        )
        original = original.model_copy(
            update={
                "ai_interpretation": original.ai_interpretation.model_copy(
                    update={"missing_context": ["상시근로자 수"]}
                )
            }
        )
        await InMemoryResultRepository(store).save_many([original])

        snapshot_repo = InMemorySnapshotRepository(store)
        await snapshot_repo.save(a_snapshot())

        analyzer = FakeAnalyzer(store, analysis.analysis_id)
        monkeypatch.setattr(
            "app.services.reassess_service.analyze_article", analyzer
        )

        service = ReassessService(
            snapshot_repo=snapshot_repo,
            result_repo=InMemoryResultRepository(store),
            revision_repo=InMemoryRevisionRepository(store),
        )
        # LLM은 쓰이지 않지만 속성 접근은 막는다.
        service._llm = object()
        return store, original, service, analyzer

    return prepare


class TestOverrides:
    def test_인원을_덮어쓴다(self):
        context = apply_overrides(a_profile(None), ReassessInput(employee_count=80))
        assert context.employee_count == 80

    def test_자유_서술은_직무에_덧붙인다(self):
        context = apply_overrides(
            a_profile(80), ReassessInput(notes="우리는 제조업이 아닙니다")
        )
        assert "제조업이 아닙니다" in context.job

    def test_프로필_자체는_바뀌지_않는다(self):
        """과거 분석은 당시 프로필 기준으로 보존되어야 한다 (FR-002 AC)."""
        profile = a_profile(None)
        apply_overrides(profile, ReassessInput(employee_count=80))
        assert profile.employee_count is None

    def test_빈_입력_판별(self):
        assert ReassessInput().is_empty
        assert ReassessInput(notes="   ").is_empty
        assert not ReassessInput(employee_count=0).is_empty

    def test_이력에_남길_정보를_만든다(self):
        added = ReassessInput(employee_count=80, notes="추가 설명").to_context_map()
        assert added == {"상시근로자 수": "80", "추가 설명": "추가 설명"}


class TestReassess:
    async def test_보류가_해당으로_바뀐다(self, setup):
        store, original, service, _ = await setup()

        outcome = await service.reassess(
            original=original,
            profile=a_profile(None),
            payload=ReassessInput(employee_count=80),
            user_id="u1",
        )

        assert outcome.changed
        assert outcome.result.applicability is Applicability.APPLICABLE
        assert "HOLD → APPLICABLE" in outcome.summary

    async def test_기존_결과를_덮어쓰지_않는다(self, setup):
        """BR-008. 판정 변화를 추적할 수 있어야 한다."""
        store, original, service, _ = await setup()

        outcome = await service.reassess(
            original=original,
            profile=a_profile(None),
            payload=ReassessInput(employee_count=80),
            user_id="u1",
        )

        kept = await InMemoryResultRepository(store).get(original.result_id, "u1")
        assert kept is not None
        assert kept.applicability is Applicability.HOLD  # 원본은 그대로
        assert outcome.result.result_id != original.result_id  # 새 결과

    async def test_이력이_기록된다(self, setup):
        store, original, service, _ = await setup()

        outcome = await service.reassess(
            original=original,
            profile=a_profile(None),
            payload=ReassessInput(employee_count=80),
            user_id="u1",
        )

        revisions = await InMemoryRevisionRepository(store).list_for_result(
            original.result_id, "u1"
        )
        assert len(revisions) == 1
        assert revisions[0].previous_applicability is Applicability.HOLD
        assert revisions[0].new_applicability is Applicability.APPLICABLE
        assert revisions[0].added_context == {"상시근로자 수": "80"}
        assert outcome.revision.revision_id == revisions[0].revision_id

    async def test_분석_당시_법령_근거를_쓴다(self, setup):
        """AP-07. 그 사이 법령이 또 개정됐어도 같은 근거로 판단한다."""
        store, original, service, analyzer = await setup()

        await service.reassess(
            original=original,
            profile=a_profile(None),
            payload=ReassessInput(employee_count=80),
            user_id="u1",
        )

        packet = analyzer.calls[0]
        assert packet.law.original_text == ARTICLE_TEXT
        assert packet.law.law_name == "근로기준법"

    async def test_최초_분석의_변경내용을_재사용한다(self, setup):
        """BR-006. 신구법을 다시 부르면 다른 근거로 판단하게 된다."""
        store, original, service, analyzer = await setup()

        await service.reassess(
            original=original,
            profile=a_profile(None),
            payload=ReassessInput(employee_count=80),
            user_id="u1",
        )

        packet = analyzer.calls[0]
        assert packet.change.change_type is original.change.change_type
        assert packet.change.additions == original.change.additions

    async def test_판정이_그대로면_changed는_False(self, setup):
        store, original, service, _ = await setup()

        outcome = await service.reassess(
            original=original,
            profile=a_profile(None),
            payload=ReassessInput(employee_count=3),  # 여전히 기준 미달
            user_id="u1",
        )

        assert not outcome.changed
        assert "그대로입니다" in outcome.summary


class TestGuards:
    async def test_보류가_아니면_거부(self, setup):
        store, _, service, _ = await setup()
        applicable = make_result(analysis_id="a1")

        with pytest.raises(NotHoldError):
            await service.reassess(
                original=applicable,
                profile=a_profile(80),
                payload=ReassessInput(employee_count=80),
                user_id="u1",
            )

    async def test_빈_입력은_거부(self, setup):
        store, original, service, _ = await setup()

        with pytest.raises(ReassessError, match="추가 정보"):
            await service.reassess(
                original=original,
                profile=a_profile(None),
                payload=ReassessInput(),
                user_id="u1",
            )

    async def test_근거가_없으면_거부(self, setup):
        """BR-001. 없는 근거로 다시 판단하느니 실패를 드러낸다."""
        store, original, service, _ = await setup()
        store.snapshots.clear()

        with pytest.raises(SnapshotMissingError):
            await service.reassess(
                original=original,
                profile=a_profile(None),
                payload=ReassessInput(employee_count=80),
                user_id="u1",
            )
