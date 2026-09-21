"""결과·근거·피드백·저장 API 테스트 (FR-012~014, FR-017, FR-019)."""

import pytest

from app.domain.entities import Analysis
from app.repositories.memory import InMemoryAnalysisRepository, InMemoryResultRepository
from tests.conftest import make_result


@pytest.fixture
async def saved_result(store):
    """분석 1건과 결과 1건을 user-a 소유로 심는다."""
    analysis = await InMemoryAnalysisRepository(store).create(Analysis(user_id="user-a"))
    result = make_result(analysis_id=analysis.analysis_id)
    await InMemoryResultRepository(store).save_many([result])
    return result


class TestResultDetail:
    async def test_상세_조회(self, client, saved_result):
        r = await client.get(f"/api/v1/results/{saved_result.result_id}")
        assert r.status_code == 200
        assert r.json()["legal_evidence"]["article_no"] == "제93조"

    async def test_없는_결과는_404(self, client):
        assert (await client.get("/api/v1/results/nope")).status_code == 404

    async def test_남의_결과는_404(self, client, saved_result):
        r = await client.get(
            f"/api/v1/results/{saved_result.result_id}", headers={"X-User-Id": "user-b"}
        )
        assert r.status_code == 404


class TestEvidence:
    """AP-05 / FR-014. 근거의 성격이 섞이지 않아야 한다."""

    async def test_세_근거가_별도_키로_나온다(self, client, saved_result):
        r = await client.get(f"/api/v1/results/{saved_result.result_id}/evidence")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"legal_evidence", "reference_evidence", "ai_interpretation"}

    async def test_법적근거는_공식값만_담는다(self, client, saved_result):
        body = (await client.get(
            f"/api/v1/results/{saved_result.result_id}/evidence"
        )).json()
        legal = body["legal_evidence"]
        assert legal["law_name"] == "근로기준법"
        assert legal["effective_date"] == "2026-08-20"
        assert legal["ministry"] == "고용노동부"

    async def test_인용은_검증_통과분만_담긴다(self, client, saved_result):
        body = (await client.get(
            f"/api/v1/results/{saved_result.result_id}/evidence"
        )).json()
        assert body["legal_evidence"]["quoted_spans"] == [
            "상시 10명 이상의 근로자를 사용하는 사용자는"
        ]

    async def test_AI해석에_공식_사실필드가_없다(self, client, saved_result):
        """FR-020. 응답 계약 수준에서도 자리가 없다."""
        body = (await client.get(
            f"/api/v1/results/{saved_result.result_id}/evidence"
        )).json()
        ai = body["ai_interpretation"]
        for forbidden in ("law_name", "article_no", "effective_date", "ministry", "source_url"):
            assert forbidden not in ai

    async def test_RAG가_없으면_빈_배열(self, client, saved_result):
        """BR-005. 참고자료 없음은 정상 상태다."""
        body = (await client.get(
            f"/api/v1/results/{saved_result.result_id}/evidence"
        )).json()
        assert body["reference_evidence"] == []

    async def test_법률자문_아님_고지가_포함된다(self, client, saved_result):
        """NFR-015."""
        body = (await client.get(
            f"/api/v1/results/{saved_result.result_id}/evidence"
        )).json()
        assert "법률 자문이 아니" in body["disclaimer"]

    async def test_남의_결과_근거는_404(self, client, saved_result):
        r = await client.get(
            f"/api/v1/results/{saved_result.result_id}/evidence",
            headers={"X-User-Id": "user-b"},
        )
        assert r.status_code == 404


class TestFeedback:
    async def test_피드백_제출(self, client, saved_result):
        r = await client.post(
            f"/api/v1/results/{saved_result.result_id}/feedback",
            json={"helpful": False, "correction_type": "wrong_applicability",
                  "comment": "우리 회사는 해당 안 됩니다"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["helpful"] is False
        assert body["correction_type"] == "wrong_applicability"
        assert "user_id" not in body  # 응답에 소유자를 되돌려주지 않는다

    async def test_없는_결과에는_피드백_불가(self, client):
        r = await client.post("/api/v1/results/nope/feedback", json={"helpful": True})
        assert r.status_code == 404

    async def test_남의_결과에는_피드백_불가(self, client, saved_result):
        r = await client.post(
            f"/api/v1/results/{saved_result.result_id}/feedback",
            json={"helpful": True},
            headers={"X-User-Id": "user-b"},
        )
        assert r.status_code == 404


class TestSavedRegulations:
    async def test_저장하면_법령_정보가_함께_기록된다(self, client, saved_result):
        r = await client.post(
            "/api/v1/saved-regulations",
            json={"result_id": saved_result.result_id, "note": "9월까지 검토"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["law_name"] == "근로기준법"
        assert body["article_no"] == "제93조"
        assert body["note"] == "9월까지 검토"

    async def test_목록_조회와_삭제(self, client, saved_result):
        created = (await client.post(
            "/api/v1/saved-regulations", json={"result_id": saved_result.result_id}
        )).json()

        assert len((await client.get("/api/v1/saved-regulations")).json()) == 1
        assert (await client.delete(
            f"/api/v1/saved-regulations/{created['saved_id']}"
        )).status_code == 204
        assert (await client.get("/api/v1/saved-regulations")).json() == []

    async def test_남의_저장목록은_보이지_않는다(self, client, saved_result):
        await client.post(
            "/api/v1/saved-regulations", json={"result_id": saved_result.result_id}
        )
        r = await client.get("/api/v1/saved-regulations", headers={"X-User-Id": "user-b"})
        assert r.json() == []

    async def test_남의_저장항목은_삭제할_수_없다(self, client, saved_result):
        created = (await client.post(
            "/api/v1/saved-regulations", json={"result_id": saved_result.result_id}
        )).json()
        r = await client.delete(
            f"/api/v1/saved-regulations/{created['saved_id']}",
            headers={"X-User-Id": "user-b"},
        )
        assert r.status_code == 404


class TestReassessApi:
    """FR-008 재판정 API."""

    @pytest.fixture
    async def hold_result(self, store):
        """보류 결과와 법령 근거를 심는다."""
        import datetime as dt

        from app.adapters.law.models import LawArticle, LawSnapshot
        from app.domain.enums import Applicability, ResultStatus
        from app.repositories.memory import InMemorySnapshotRepository

        analysis = await InMemoryAnalysisRepository(store).create(
            Analysis(user_id="user-a")
        )
        result = make_result(
            analysis_id=analysis.analysis_id,
            applicability=Applicability.HOLD,
            action_grade=None,
            status=ResultStatus.HOLD,
        )
        result = result.model_copy(
            update={
                "ai_interpretation": result.ai_interpretation.model_copy(
                    update={"missing_context": ["상시근로자 수"]}
                )
            }
        )
        await InMemoryResultRepository(store).save_many([result])
        await InMemorySnapshotRepository(store).save(
            LawSnapshot(
                law_id="001872",
                law_name="근로기준법",
                effective_date=dt.date(2026, 8, 20),
                articles=[
                    LawArticle(
                        article_no="제93조",
                        article_title="취업규칙의 작성ㆍ신고",
                        original_text="상시 10명 이상의 근로자를 사용하는 사용자는…",
                    )
                ],
            )
        )
        return result

    async def test_프로필이_없으면_거부(self, client, hold_result):
        r = await client.post(
            f"/api/v1/results/{hold_result.result_id}/reassess",
            json={"employee_count": 80},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "profile_required"

    async def test_빈_입력은_거부(self, client, hold_result):
        await client.put(
            "/api/v1/profile",
            json={"job": "HR", "industry": "IT", "company_size": "MEDIUM"},
        )
        r = await client.post(
            f"/api/v1/results/{hold_result.result_id}/reassess", json={}
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "reassess_not_allowed"

    async def test_없는_결과는_404(self, client):
        r = await client.post(
            "/api/v1/results/nope/reassess", json={"employee_count": 80}
        )
        assert r.status_code == 404

    async def test_남의_결과는_404(self, client, hold_result):
        r = await client.post(
            f"/api/v1/results/{hold_result.result_id}/reassess",
            json={"employee_count": 80},
            headers={"X-User-Id": "user-b"},
        )
        assert r.status_code == 404

    async def test_알_수_없는_필드는_거부(self, client, hold_result):
        r = await client.post(
            f"/api/v1/results/{hold_result.result_id}/reassess",
            json={"employee_count": 80, "is_admin": True},
        )
        assert r.status_code == 422

    async def test_이력_조회(self, client, hold_result):
        r = await client.get(f"/api/v1/results/{hold_result.result_id}/revisions")
        assert r.status_code == 200
        assert r.json() == []

    async def test_남의_이력은_404(self, client, hold_result):
        r = await client.get(
            f"/api/v1/results/{hold_result.result_id}/revisions",
            headers={"X-User-Id": "user-b"},
        )
        assert r.status_code == 404
