from pathlib import Path

import pytest

from app.core.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def law_settings() -> Settings:
    return Settings(
        law_api_oc="testoc",
        law_api_base_url="https://www.law.go.kr/DRF",
        law_api_max_retries=1,
        openai_api_key="",
    )


# ── API 테스트 지원 ────────────────────────────────────────────────────

import datetime as _dt  # noqa: E402

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.api import deps as _deps  # noqa: E402
from app.domain.enums import (  # noqa: E402
    ActionGrade,
    Applicability,
    ChangeType,
    ResultStatus,
)
from app.domain.result import (  # noqa: E402
    AiInterpretation,
    AnalysisResult,
    ChangeSummary,
    LegalEvidence,
    ValidationReport,
)
from app.main import create_app  # noqa: E402


@pytest.fixture
def api_settings() -> Settings:
    """API 테스트용 설정.

    storage/database_url을 **명시적으로** 지정한다. Settings()는 지정하지 않은
    필드를 .env에서 읽으므로, 명시하지 않으면 테스트가 개발자의 로컬 .env에
    좌우된다. 실제로 .env를 postgres로 바꾸자 전체 API 테스트가 깨진 적이 있다.
    """
    return Settings(
        app_env="local",
        auth_mode="dev",
        dev_user_id="user-a",
        law_api_oc="testoc",
        openai_api_key="test-key",
        storage="memory",
        database_url="",
        supabase_url="",
        supabase_jwt_secret="",
    )


@pytest.fixture
def store():
    """테스트마다 깨끗한 인메모리 저장소."""
    s = _deps.get_store()
    s.clear()
    yield s
    s.clear()


@pytest.fixture
def app(api_settings, store):
    from app.core.config import get_settings as _get_settings

    application = create_app(api_settings)
    application.dependency_overrides[_get_settings] = lambda: api_settings
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Id": "user-a"}
    ) as c:
        yield c


def make_result(
    *,
    analysis_id: str,
    applicability: Applicability = Applicability.APPLICABLE,
    action_grade: ActionGrade | None = ActionGrade.ACTION,
    status: ResultStatus = ResultStatus.VALIDATED,
    law_name: str = "근로기준법",
    article_no: str = "제93조",
) -> AnalysisResult:
    """테스트용 결과. AI/네트워크를 타지 않는다."""
    return AnalysisResult(
        analysis_id=analysis_id,
        status=status,
        applicability=applicability,
        action_grade=action_grade,
        change=ChangeSummary(change_type=ChangeType.AMENDED, additions=["변경"]),
        legal_evidence=LegalEvidence(
            law_id="001872", law_name=law_name, article_no=article_no,
            article_title="취업규칙의 작성ㆍ신고",
            effective_date=_dt.date(2026, 8, 20), ministry="고용노동부",
            quoted_spans=["상시 10명 이상의 근로자를 사용하는 사용자는"],
        ),
        ai_interpretation=AiInterpretation(
            reason="상시 80명이므로 해당합니다.",
            impact_summary="취업규칙을 점검해야 합니다.",
            confidence=0.9, model="test-model",
        ),
        validation=ValidationReport(passed=True, checks={"citation": True}),
    )
