"""분석 API 테스트 (FR-003, FR-015, FR-016, FR-018, NFR-007)."""

from datetime import UTC, datetime

import pytest

from app.api import deps
from app.domain.enums import ActionGrade, AnalysisStatus, Applicability, ResultStatus
from tests.conftest import make_result

PROFILE = {
    "job": "HR 담당자",
    "industry": "IT 서비스",
    "company_size": "MEDIUM",
    "employee_count": 80,
}


class FakeRunner:
    """네트워크·LLM 없이 분석 완료를 흉내낸다."""

    def __init__(self, store, results_spec=None, should_fail=False):
        self.store = store
        self.results_spec = results_spec if results_spec is not None else [{}]
        self.should_fail = should_fail
        self.calls = 0

    async def run(self, analysis, profile, *, max_laws=3):
        from app.repositories.memory import (
            InMemoryAnalysisRepository,
            InMemoryResultRepository,
        )
        from app.services.analysis_runner import summarize

        self.calls += 1
        analysis_repo = InMemoryAnalysisRepository(self.store)
        result_repo = InMemoryResultRepository(self.store)

        if self.should_fail:
            return await self.fail(analysis, "법령 데이터를 가져오지 못했습니다.")

        results = [
            make_result(analysis_id=analysis.analysis_id, **spec)
            for spec in self.results_spec
        ]
        await result_repo.save_many(results)
        return await analysis_repo.update(
            analysis.model_copy(
                update={
                    "status": AnalysisStatus.COMPLETED,
                    "completed_at": datetime.now(UTC),
                    "laws_examined": 1,
                    "articles_changed": len(results),
                    "counts": summarize(results),
                }
            )
        )

    async def fail(self, analysis, message):
        from app.repositories.memory import InMemoryAnalysisRepository

        return await InMemoryAnalysisRepository(self.store).update(
            analysis.model_copy(
                update={
                    "status": AnalysisStatus.FAILED,
                    "completed_at": datetime.now(UTC),
                    "error": message,
                }
            )
        )


@pytest.fixture
def use_runner(app, store):
    def _install(**kwargs):
        runner = FakeRunner(store, **kwargs)
        app.dependency_overrides[deps.get_analysis_runner] = lambda: runner
        return runner

    return _install


@pytest.fixture
async def with_profile(client):
    await client.put("/api/v1/profile", json=PROFILE)


class TestCreateAnalysis:
    async def test_프로필이_없으면_거부(self, client, use_runner):
        use_runner()
        r = await client.post("/api/v1/analyses", json={})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "profile_required"

    async def test_생성시_202와_analysis_id(self, client, with_profile, use_runner):
        use_runner()
        r = await client.post("/api/v1/analyses", json={})
        assert r.status_code == 202
        body = r.json()
        assert body["analysis_id"]
        assert body["trace_id"]

    async def test_백그라운드_실행후_완료된다(self, client, with_profile, use_runner):
        runner = use_runner()
        created = (await client.post("/api/v1/analyses", json={})).json()

        got = (await client.get(f"/api/v1/analyses/{created['analysis_id']}")).json()
        assert got["status"] == AnalysisStatus.COMPLETED.value
        assert got["completed_at"] is not None
        assert runner.calls == 1

    async def test_중복_실행_방지(self, client, with_profile, use_runner, store):
        """FR-003 AC. 진행 중인 분석이 있으면 새로 시작하지 않는다."""
        use_runner()
        first = (await client.post("/api/v1/analyses", json={})).json()

        # 진행 중 상태를 인위적으로 만든다
        analysis = store.analyses[first["analysis_id"]]
        store.analyses[first["analysis_id"]] = analysis.model_copy(
            update={"status": AnalysisStatus.RUNNING}
        )

        r = await client.post("/api/v1/analyses", json={})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "analysis_in_progress"
        assert first["analysis_id"] in r.json()["error"]["detail"]

    async def test_기간_역순은_거부(self, client, with_profile, use_runner):
        use_runner()
        r = await client.post(
            "/api/v1/analyses",
            json={"period_from": "2026-09-01", "period_to": "2026-01-01"},
        )
        assert r.status_code == 422

    async def test_실패는_FAILED와_사용자용_사유를_남긴다(self, client, with_profile, use_runner):
        """NFR-005. 실패를 성공으로 위장하지 않는다."""
        use_runner(should_fail=True)
        created = (await client.post("/api/v1/analyses", json={})).json()

        got = (await client.get(f"/api/v1/analyses/{created['analysis_id']}")).json()
        assert got["status"] == AnalysisStatus.FAILED.value
        assert "법령 데이터를 가져오지 못했습니다." in got["error"]


class TestResults:
    async def test_집계가_행동등급별로_분리된다(self, client, with_profile, use_runner):
        use_runner(results_spec=[
            {"action_grade": ActionGrade.ACTION},
            {"action_grade": ActionGrade.DECISION},
            {"applicability": Applicability.HOLD, "action_grade": None,
             "status": ResultStatus.HOLD},
            {"applicability": Applicability.NOT_APPLICABLE, "action_grade": None},
        ])
        created = (await client.post("/api/v1/analyses", json={})).json()

        r = await client.get(f"/api/v1/analyses/{created['analysis_id']}/results")
        counts = r.json()["counts"]
        assert counts["action"] == 1
        assert counts["decision"] == 1
        assert counts["hold"] == 1
        assert counts["not_applicable"] == 1
        assert counts["total"] == 4

    async def test_무관은_기본적으로_숨겨진다(self, client, with_profile, use_runner):
        """FR-015. 무관 항목은 요청해야 보인다."""
        use_runner(results_spec=[
            {"action_grade": ActionGrade.ACTION},
            {"applicability": Applicability.NOT_APPLICABLE, "action_grade": None},
        ])
        created = (await client.post("/api/v1/analyses", json={})).json()
        url = f"/api/v1/analyses/{created['analysis_id']}/results"

        default = (await client.get(url)).json()
        assert len(default["items"]) == 1

        expanded = (await client.get(url, params={"include_not_applicable": True})).json()
        assert len(expanded["items"]) == 2

    async def test_검증실패_결과는_기본적으로_숨겨진다(self, client, with_profile, use_runner):
        """FR-022. 검증을 통과하지 못한 결과는 정상 결과로 보이지 않는다."""
        use_runner(results_spec=[
            {"action_grade": ActionGrade.ACTION},
            {"status": ResultStatus.REJECTED, "action_grade": None},
        ])
        created = (await client.post("/api/v1/analyses", json={})).json()
        url = f"/api/v1/analyses/{created['analysis_id']}/results"

        default = (await client.get(url)).json()
        expanded = (await client.get(url, params={"include_rejected": True})).json()
        assert len(default["items"]) == 1
        assert len(expanded["items"]) == 2

    async def test_ACTION이_AWARENESS보다_먼저_온다(self, client, with_profile, use_runner):
        """FR-015. 사용자가 '지금 할 일'을 먼저 보게 한다."""
        use_runner(results_spec=[
            {"action_grade": ActionGrade.AWARENESS, "article_no": "제1조"},
            {"applicability": Applicability.HOLD, "action_grade": None,
             "status": ResultStatus.HOLD, "article_no": "제2조"},
            {"action_grade": ActionGrade.ACTION, "article_no": "제3조"},
            {"action_grade": ActionGrade.DECISION, "article_no": "제4조"},
        ])
        created = (await client.post("/api/v1/analyses", json={})).json()

        r = await client.get(f"/api/v1/analyses/{created['analysis_id']}/results")
        grades = [i["action_grade"] for i in r.json()["items"]]
        assert grades == ["ACTION", "DECISION", "AWARENESS", None]

    async def test_결과에_법적근거와_AI해석이_분리되어_있다(self, client, with_profile, use_runner):
        """AP-05/FR-014. 응답 형태만으로 무엇이 공식이고 무엇이 해석인지 구분된다."""
        use_runner()
        created = (await client.post("/api/v1/analyses", json={})).json()
        item = (await client.get(
            f"/api/v1/analyses/{created['analysis_id']}/results"
        )).json()["items"][0]

        assert item["legal_evidence"]["law_name"] == "근로기준법"
        assert item["legal_evidence"]["quoted_spans"]
        assert item["ai_interpretation"]["reason"]
        # AI 해석 블록에 공식 사실 필드가 없어야 한다 (FR-020)
        for forbidden in ("law_name", "article_no", "effective_date"):
            assert forbidden not in item["ai_interpretation"]


class TestHistoryAndIsolation:
    async def test_히스토리는_최신순(self, client, with_profile, use_runner, store):
        use_runner()
        ids = []
        for _ in range(3):
            ids.append((await client.post("/api/v1/analyses", json={})).json()["analysis_id"])

        r = await client.get("/api/v1/analyses")
        body = r.json()
        assert body["total"] == 3
        assert [i["analysis_id"] for i in body["items"]] == list(reversed(ids))

    async def test_페이지네이션(self, client, with_profile, use_runner):
        use_runner()
        for _ in range(3):
            await client.post("/api/v1/analyses", json={})

        r = await client.get("/api/v1/analyses", params={"limit": 2, "offset": 1})
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3

    async def test_남의_분석은_404(self, client, with_profile, use_runner):
        """NFR-007. 존재 여부조차 알려주지 않는다."""
        use_runner()
        created = (await client.post("/api/v1/analyses", json={})).json()

        r = await client.get(
            f"/api/v1/analyses/{created['analysis_id']}", headers={"X-User-Id": "user-b"}
        )
        assert r.status_code == 404

    async def test_남의_분석_결과도_404(self, client, with_profile, use_runner):
        use_runner()
        created = (await client.post("/api/v1/analyses", json={})).json()

        r = await client.get(
            f"/api/v1/analyses/{created['analysis_id']}/results",
            headers={"X-User-Id": "user-b"},
        )
        assert r.status_code == 404

    async def test_히스토리에_남의_분석이_섞이지_않는다(self, client, with_profile, use_runner):
        use_runner()
        await client.post("/api/v1/analyses", json={})

        r = await client.get("/api/v1/analyses", headers={"X-User-Id": "user-b"})
        assert r.json()["total"] == 0


class TestCancel:
    async def test_진행중_분석_취소(self, client, with_profile, use_runner, store):
        """멈춘 분석이 새 실행을 영구히 막지 않도록."""
        use_runner()
        created = (await client.post("/api/v1/analyses", json={})).json()
        aid = created["analysis_id"]
        store.analyses[aid] = store.analyses[aid].model_copy(
            update={"status": AnalysisStatus.RUNNING}
        )

        assert (await client.delete(f"/api/v1/analyses/{aid}")).status_code == 204
        got = (await client.get(f"/api/v1/analyses/{aid}")).json()
        assert got["status"] == AnalysisStatus.FAILED.value

        # 취소 후에는 새 분석을 시작할 수 있다
        assert (await client.post("/api/v1/analyses", json={})).status_code == 202


class TestDailyLimit:
    """공개 배포에서 AI 호출 비용을 유한하게 묶는다.

    '동시 1건' 제약(uq_analyses_one_active_per_user)은 중복 클릭만 막는다.
    하루에 몇 번이든 돌리는 것은 막지 못하므로, 가입이 열린 배포에서는 그것이
    곧 OpenAI 키를 열어 두는 것과 같다. 분석 1회가 약 6만 토큰이다.
    """

    @staticmethod
    def _limit(app, *, per_user: int = 0, total: int = 0):
        """상한만 바꾼다. conftest가 넣어 둔 테스트 설정(dev 인증·메모리 저장소)을
        그대로 이어받아야 하므로 get_settings()를 새로 읽지 않는다."""
        from app.core.config import get_settings

        base = app.dependency_overrides[get_settings]()
        patched = base.model_copy(
            update={
                "daily_analysis_limit_per_user": per_user,
                "daily_analysis_limit_total": total,
            }
        )
        app.dependency_overrides[get_settings] = lambda: patched

    async def test_사용자_상한에_걸리면_429(self, app, client, with_profile, use_runner):
        use_runner()
        self._limit(app, per_user=2)

        for _ in range(2):
            assert (await client.post("/api/v1/analyses", json={})).status_code == 202

        r = await client.post("/api/v1/analyses", json={})
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "daily_limit_exceeded"

    async def test_전체_상한은_계정을_바꿔도_걸린다(self, app, client, with_profile, use_runner):
        """계정을 여러 개 만들어 우회하는 경우를 막는다."""
        use_runner()
        self._limit(app, per_user=0, total=1)

        assert (await client.post("/api/v1/analyses", json={})).status_code == 202
        r = await client.post("/api/v1/analyses", json={})
        assert r.status_code == 429
        assert "전체" in r.json()["error"]["message"]

    async def test_상한이_0이면_제한하지_않는다(self, app, client, with_profile, use_runner):
        """로컬 개발과 평가 실행은 상한 없이 돌아야 한다."""
        use_runner()
        self._limit(app, per_user=0, total=0)
        for _ in range(3):
            assert (await client.post("/api/v1/analyses", json={})).status_code == 202

    async def test_사용자_상한은_남의_분석을_세지_않는다(
        self, app, client, with_profile, use_runner, store
    ):
        from app.domain.entities import Analysis

        use_runner()
        self._limit(app, per_user=1, total=0)

        other = Analysis(user_id="someone-else")
        store.analyses[other.analysis_id] = other

        assert (await client.post("/api/v1/analyses", json={})).status_code == 202
