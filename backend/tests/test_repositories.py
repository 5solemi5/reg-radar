"""저장소 계약 테스트 (NFR-007, NFR-011).

**같은 테스트를 인메모리와 Postgres 양쪽에 돌린다.** 저장소는 교체 가능해야
하는데, 구현마다 다른 테스트를 쓰면 미묘한 동작 차이가 숨는다. 실제로
W4 이후 인메모리로 통과한 코드가 Postgres에서 깨지는 일을 막으려는 것이다.

Postgres 테스트는 DB가 없으면 건너뛴다. 조용히 통과한 것처럼 보이지 않도록
skip 사유를 명시한다.
"""

import os

import pytest

from app.domain.entities import Analysis, Feedback, Profile, ResultCounts, SavedRegulation
from app.domain.enums import ActionGrade, AnalysisStatus, Applicability, CompanySize
from app.repositories.db import Database, DatabaseUnavailableError
from app.repositories.memory import (
    InMemoryAnalysisRepository,
    InMemoryFeedbackRepository,
    InMemoryProfileRepository,
    InMemoryResultRepository,
    InMemorySavedRegulationRepository,
    InMemoryStore,
)
from app.repositories.postgres import (
    PostgresAnalysisRepository,
    PostgresFeedbackRepository,
    PostgresProfileRepository,
    PostgresResultRepository,
    PostgresSavedRegulationRepository,
)
from tests.conftest import make_result

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://127.0.0.1:5432/regradar_test"
)

TABLES = [
    "hold_revisions", "feedback", "saved_regulations",
    "analysis_results", "analyses", "profiles", "law_snapshots",
]


@pytest.fixture
async def database():
    """테스트마다 풀을 새로 연다.

    asyncpg 풀은 생성된 이벤트 루프에 묶인다. pytest-asyncio는 테스트마다 새
    루프를 만들므로, 풀을 모듈 스코프로 공유하면 'attached to a different loop'
    에러가 난다. 로컬 Postgres 연결은 저렴하므로 정확성을 택한다.
    """
    from app.core.config import Settings

    db = Database(
        Settings(database_url=TEST_DATABASE_URL, storage="postgres", db_pool_max=2)
    )
    try:
        await db.connect()
    except DatabaseUnavailableError as exc:
        pytest.skip(f"Postgres를 사용할 수 없습니다 ({exc}). TEST_DATABASE_URL 확인.")
    yield db
    await db.disconnect()


@pytest.fixture
def mem_store():
    store = InMemoryStore()
    yield store
    store.clear()


# ── 양쪽 구현에 같은 테스트를 돌리기 위한 팩토리 ────────────────────────


@pytest.fixture(params=["memory", "postgres"])
async def repos(request, mem_store, database):
    """(profile, analysis, result, saved, feedback) 저장소 묶음."""
    if request.param == "memory":
        yield {
            "kind": "memory",
            "profile": InMemoryProfileRepository(mem_store),
            "analysis": InMemoryAnalysisRepository(mem_store),
            "result": InMemoryResultRepository(mem_store),
            "saved": InMemorySavedRegulationRepository(mem_store),
            "feedback": InMemoryFeedbackRepository(mem_store),
        }
    else:
        await database.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        yield {
            "kind": "postgres",
            "profile": PostgresProfileRepository(database),
            "analysis": PostgresAnalysisRepository(database),
            "result": PostgresResultRepository(database),
            "saved": PostgresSavedRegulationRepository(database),
            "feedback": PostgresFeedbackRepository(database),
        }


def a_profile(user_id: str = "u1", **kwargs) -> Profile:
    return Profile(
        user_id=user_id,
        job=kwargs.get("job", "HR 담당자"),
        industry=kwargs.get("industry", "IT 서비스"),
        company_size=kwargs.get("company_size", CompanySize.MEDIUM),
        employee_count=kwargs.get("employee_count", 80),
        interests=kwargs.get("interests", ["노동·인사"]),
    )


class TestProfileRepository:
    async def test_저장후_조회(self, repos):
        await repos["profile"].upsert(a_profile())
        found = await repos["profile"].get("u1")
        assert found is not None
        assert found.job == "HR 담당자"
        assert found.employee_count == 80
        assert found.interests == ["노동·인사"]

    async def test_없으면_None(self, repos):
        assert await repos["profile"].get("nobody") is None

    async def test_재저장시_created_at_유지(self, repos):
        first = await repos["profile"].upsert(a_profile())
        second = await repos["profile"].upsert(a_profile(job="총무"))
        assert second.created_at == first.created_at
        assert second.job == "총무"

    async def test_상시근로자_수는_비울_수_있다(self, repos):
        """미입력은 유효한 상태이며 보류 사유가 된다."""
        await repos["profile"].upsert(a_profile(employee_count=None))
        found = await repos["profile"].get("u1")
        assert found.employee_count is None

    async def test_사용자별로_분리된다(self, repos):
        await repos["profile"].upsert(a_profile("u1"))
        await repos["profile"].upsert(a_profile("u2", job="쇼핑몰 운영"))
        assert (await repos["profile"].get("u1")).job == "HR 담당자"
        assert (await repos["profile"].get("u2")).job == "쇼핑몰 운영"


class TestAnalysisRepository:
    async def test_생성후_조회(self, repos):
        created = await repos["analysis"].create(Analysis(user_id="u1"))
        found = await repos["analysis"].get(created.analysis_id, "u1")
        assert found is not None
        assert found.status is AnalysisStatus.CREATED

    async def test_남의_분석은_None(self, repos):
        """NFR-007. 존재 여부조차 알려주지 않는다."""
        created = await repos["analysis"].create(Analysis(user_id="u1"))
        assert await repos["analysis"].get(created.analysis_id, "u2") is None

    async def test_잘못된_id는_None(self, repos):
        assert await repos["analysis"].get("not-a-uuid", "u1") is None

    async def test_상태_갱신(self, repos):
        created = await repos["analysis"].create(Analysis(user_id="u1"))
        updated = await repos["analysis"].update(
            created.model_copy(
                update={
                    "status": AnalysisStatus.COMPLETED,
                    "laws_examined": 3,
                    "articles_changed": 12,
                    "counts": ResultCounts(action=1, hold=9, awareness=2),
                }
            )
        )
        assert updated.status is AnalysisStatus.COMPLETED
        assert updated.counts.action == 1
        assert updated.counts.hold == 9
        assert updated.counts.total == 12

    async def _completed_analyses(self, repos, count: int, user_id="u1") -> list[str]:
        """분석을 만들고 완료 처리한다.

        진행 중인 분석은 사용자당 하나만 허용되므로(FR-003), 실제 사용 흐름대로
        완료한 뒤 다음 것을 만든다.
        """
        ids = []
        for _ in range(count):
            created = await repos["analysis"].create(Analysis(user_id=user_id))
            await repos["analysis"].update(
                created.model_copy(update={"status": AnalysisStatus.COMPLETED})
            )
            ids.append(created.analysis_id)
        return ids

    async def test_히스토리는_최신순(self, repos):
        ids = await self._completed_analyses(repos, 3)
        items, total = await repos["analysis"].list_for_user("u1")
        assert total == 3
        assert [i.analysis_id for i in items] == list(reversed(ids))

    async def test_페이지네이션(self, repos):
        await self._completed_analyses(repos, 3)
        items, total = await repos["analysis"].list_for_user("u1", limit=2, offset=1)
        assert len(items) == 2
        assert total == 3

    async def test_중복_실행_방지는_DB도_강제한다(self, repos):
        """FR-003. 애플리케이션이 find_active로 막지만, 동시 요청이 겹치면
        코드만으로는 뚫린다. Postgres는 부분 유니크 인덱스로 한 번 더 막는다.

        인메모리 구현에는 이 제약이 없다 — API 계층에서만 막힌다. 저장소를
        교체해도 사용자가 보는 동작은 같지만, 방어 깊이는 다르다는 뜻이다.
        """
        await repos["analysis"].create(Analysis(user_id="u1"))

        if repos["kind"] == "postgres":
            import asyncpg

            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await repos["analysis"].create(Analysis(user_id="u1"))
        else:
            await repos["analysis"].create(Analysis(user_id="u1"))

    async def test_히스토리에_남의_것이_섞이지_않는다(self, repos):
        await repos["analysis"].create(Analysis(user_id="u1"))
        items, total = await repos["analysis"].list_for_user("u2")
        assert items == [] and total == 0

    async def test_진행중_분석_찾기(self, repos):
        created = await repos["analysis"].create(
            Analysis(user_id="u1", status=AnalysisStatus.RUNNING)
        )
        active = await repos["analysis"].find_active("u1")
        assert active is not None and active.analysis_id == created.analysis_id

    async def test_완료된_분석은_진행중이_아니다(self, repos):
        created = await repos["analysis"].create(Analysis(user_id="u1"))
        await repos["analysis"].update(
            created.model_copy(update={"status": AnalysisStatus.COMPLETED})
        )
        assert await repos["analysis"].find_active("u1") is None


class TestResultRepository:
    async def _analysis(self, repos, user_id="u1") -> Analysis:
        return await repos["analysis"].create(Analysis(user_id=user_id))

    async def test_저장후_조회(self, repos):
        analysis = await self._analysis(repos)
        result = make_result(analysis_id=analysis.analysis_id)
        await repos["result"].save_many([result])

        found = await repos["result"].get(result.result_id, "u1")
        assert found is not None
        assert found.legal_evidence.law_name == "근로기준법"
        assert found.legal_evidence.article_no == "제93조"
        assert found.action_grade is ActionGrade.ACTION

    async def test_법적_근거가_손실없이_왕복한다(self, repos):
        """AP-07. 과거 분석을 재현하려면 근거가 그대로 남아 있어야 한다."""
        analysis = await self._analysis(repos)
        result = make_result(analysis_id=analysis.analysis_id)
        await repos["result"].save_many([result])

        found = await repos["result"].get(result.result_id, "u1")
        assert found.legal_evidence.quoted_spans == result.legal_evidence.quoted_spans
        assert found.legal_evidence.effective_date == result.legal_evidence.effective_date
        assert found.legal_evidence.ministry == result.legal_evidence.ministry

    async def test_AI_해석도_왕복한다(self, repos):
        analysis = await self._analysis(repos)
        result = make_result(analysis_id=analysis.analysis_id)
        await repos["result"].save_many([result])

        found = await repos["result"].get(result.result_id, "u1")
        assert found.ai_interpretation.reason == result.ai_interpretation.reason
        assert found.ai_interpretation.confidence == result.ai_interpretation.confidence
        assert found.ai_interpretation.model == result.ai_interpretation.model

    async def test_보류_결과의_missing_context가_보존된다(self, repos):
        analysis = await self._analysis(repos)
        result = make_result(
            analysis_id=analysis.analysis_id,
            applicability=Applicability.HOLD,
            action_grade=None,
        )
        result = result.model_copy(
            update={
                "ai_interpretation": result.ai_interpretation.model_copy(
                    update={"missing_context": ["상시근로자 수"]}
                )
            }
        )
        await repos["result"].save_many([result])

        found = await repos["result"].get(result.result_id, "u1")
        assert found.ai_interpretation.missing_context == ["상시근로자 수"]

    async def test_남의_결과는_None(self, repos):
        analysis = await self._analysis(repos)
        result = make_result(analysis_id=analysis.analysis_id)
        await repos["result"].save_many([result])
        assert await repos["result"].get(result.result_id, "u2") is None

    async def test_분석별_목록(self, repos):
        analysis = await self._analysis(repos)
        results = [
            make_result(analysis_id=analysis.analysis_id, article_no=f"제{i}조")
            for i in range(1, 4)
        ]
        await repos["result"].save_many(results)

        found = await repos["result"].list_for_analysis(analysis.analysis_id, "u1")
        assert len(found) == 3

    async def test_남의_분석_결과_목록은_비어있다(self, repos):
        analysis = await self._analysis(repos)
        await repos["result"].save_many([make_result(analysis_id=analysis.analysis_id)])
        assert await repos["result"].list_for_analysis(analysis.analysis_id, "u2") == []

    async def test_빈_목록_저장은_아무것도_하지_않는다(self, repos):
        await repos["result"].save_many([])


class TestSavedAndFeedback:
    async def _result(self, repos, user_id="u1"):
        analysis = await repos["analysis"].create(Analysis(user_id=user_id))
        result = make_result(analysis_id=analysis.analysis_id)
        await repos["result"].save_many([result])
        return result

    async def test_저장후_목록(self, repos):
        result = await self._result(repos)
        await repos["saved"].create(
            SavedRegulation(
                user_id="u1", result_id=result.result_id,
                law_id="001872", law_name="근로기준법", article_no="제93조",
                note="검토 필요",
            )
        )
        items = await repos["saved"].list_for_user("u1")
        assert len(items) == 1
        assert items[0].note == "검토 필요"

    async def test_남의_저장목록은_비어있다(self, repos):
        result = await self._result(repos)
        await repos["saved"].create(
            SavedRegulation(
                user_id="u1", result_id=result.result_id,
                law_id="1", law_name="근로기준법", article_no="제93조",
            )
        )
        assert await repos["saved"].list_for_user("u2") == []

    async def test_삭제(self, repos):
        result = await self._result(repos)
        saved = await repos["saved"].create(
            SavedRegulation(
                user_id="u1", result_id=result.result_id,
                law_id="1", law_name="근로기준법", article_no="제93조",
            )
        )
        assert await repos["saved"].delete(saved.saved_id, "u1") is True
        assert await repos["saved"].list_for_user("u1") == []

    async def test_남의_항목은_삭제할_수_없다(self, repos):
        result = await self._result(repos)
        saved = await repos["saved"].create(
            SavedRegulation(
                user_id="u1", result_id=result.result_id,
                law_id="1", law_name="근로기준법", article_no="제93조",
            )
        )
        assert await repos["saved"].delete(saved.saved_id, "u2") is False
        assert len(await repos["saved"].list_for_user("u1")) == 1

    async def test_피드백_저장(self, repos):
        result = await self._result(repos)
        created = await repos["feedback"].create(
            Feedback(
                result_id=result.result_id, user_id="u1",
                helpful=False, correction_type="wrong_applicability",
                comment="우리 회사는 해당 없음",
            )
        )
        assert created.helpful is False
        found = await repos["feedback"].list_for_result(result.result_id, "u1")
        assert len(found) == 1
        assert found[0].correction_type == "wrong_applicability"
