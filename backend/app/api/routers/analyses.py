"""분석 API (FR-003, FR-015, FR-016, FR-018, UC-02/11)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.api.auth import CurrentUser, get_current_user
from app.api.deps import (
    get_analysis_repo,
    get_analysis_runner,
    get_profile_repo,
    get_result_repo,
)
from app.api.errors import (
    AnalysisInProgressError,
    ErrorResponse,
    NotFoundError,
    ProfileRequiredError,
)
from app.api.schemas import (
    AnalysisCreate,
    AnalysisListOut,
    AnalysisOut,
    CountsOut,
    ResultListOut,
    ResultOut,
)
from app.domain.entities import Analysis
from app.domain.enums import ActionGrade, AnalysisStatus, Applicability
from app.repositories.memory import (
    InMemoryAnalysisRepository,
    InMemoryProfileRepository,
    InMemoryResultRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyses", tags=["analyses"])

# 대시보드 기본 정렬 (FR-015): ACTION·DECISION을 AWARENESS보다 위에,
# 보류는 그다음, 무관은 맨 아래. 사용자가 "지금 뭘 해야 하나"를 먼저 보게 한다.
_APPLICABILITY_RANK = {
    Applicability.APPLICABLE: 0,
    Applicability.HOLD: 1,
    Applicability.NOT_APPLICABLE: 2,
}
_GRADE_RANK = {ActionGrade.ACTION: 0, ActionGrade.DECISION: 1, ActionGrade.AWARENESS: 2}


def dashboard_order(result) -> tuple[int, int, str]:
    return (
        _APPLICABILITY_RANK.get(result.applicability, 9),
        _GRADE_RANK.get(result.action_grade, 8),
        result.legal_evidence.law_name,
    )


async def _execute(runner, analysis: Analysis, profile, max_laws: int) -> None:
    """백그라운드 실행.

    예외가 태스크 밖으로 새면 분석이 RUNNING에 영원히 머물러 다음 실행까지
    막힌다. 무슨 일이 있어도 종료 상태로 보낸다 (NFR-005).
    """
    try:
        await runner.run(analysis, profile, max_laws=max_laws)
    except Exception:
        logger.exception("분석 실행 실패 analysis=%s", analysis.analysis_id)
        await runner.fail(analysis, "분석 중 오류가 발생했습니다.")


@router.post(
    "",
    response_model=AnalysisOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        409: {"model": ErrorResponse, "description": "프로필 미설정 또는 진행 중인 분석 존재"}
    },
)
async def create_analysis(
    payload: AnalysisCreate,
    background: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    profile_repo: InMemoryProfileRepository = Depends(get_profile_repo),
    analysis_repo: InMemoryAnalysisRepository = Depends(get_analysis_repo),
    runner=Depends(get_analysis_runner),
) -> AnalysisOut:
    """새 규제 분석을 시작한다.

    즉시 202와 analysis_id를 돌려주고 실제 분석은 백그라운드에서 돈다.
    분석 1건은 법령 조회 + 조문별 LLM 호출이라 수십 초가 걸릴 수 있으므로,
    동기 응답으로 묶으면 NFR-006(장시간 무응답 UI 금지)을 위반한다.
    """
    profile = await profile_repo.get(user.user_id)
    if profile is None:
        raise ProfileRequiredError()

    # FR-003 AC: 중복 클릭으로 같은 분석이 무제한 실행되지 않게 막는다.
    active = await analysis_repo.find_active(user.user_id)
    if active is not None:
        raise AnalysisInProgressError(active.analysis_id)

    analysis = await analysis_repo.create(
        Analysis(
            user_id=user.user_id,
            period_from=payload.period_from,
            period_to=payload.period_to,
            law_query=payload.law_query,
        )
    )
    background.add_task(_execute, runner, analysis, profile, payload.max_laws)
    return AnalysisOut.of(analysis)


@router.get("", response_model=AnalysisListOut)
async def list_analyses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryAnalysisRepository = Depends(get_analysis_repo),
) -> AnalysisListOut:
    """분석 히스토리 (FR-018). 최신순."""
    items, total = await repo.list_for_user(user.user_id, limit=limit, offset=offset)
    return AnalysisListOut(
        items=[AnalysisOut.of(a) for a in items], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisOut,
    responses={404: {"model": ErrorResponse}},
)
async def get_analysis(
    analysis_id: str,
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryAnalysisRepository = Depends(get_analysis_repo),
) -> AnalysisOut:
    """분석 상태 조회. 프론트는 COMPLETED/FAILED가 될 때까지 폴링한다."""
    analysis = await repo.get(analysis_id, user.user_id)
    if analysis is None:
        raise NotFoundError("분석을 찾을 수 없습니다.")
    return AnalysisOut.of(analysis)


@router.get(
    "/{analysis_id}/results",
    response_model=ResultListOut,
    responses={404: {"model": ErrorResponse}},
)
async def get_results(
    analysis_id: str,
    include_not_applicable: bool = Query(
        False, description="무관 항목 포함 여부. 기본은 제외 (FR-015)"
    ),
    include_rejected: bool = Query(
        False, description="검증 실패 결과 포함 여부. 기본은 제외 (FR-022)"
    ),
    user: CurrentUser = Depends(get_current_user),
    analysis_repo: InMemoryAnalysisRepository = Depends(get_analysis_repo),
    result_repo: InMemoryResultRepository = Depends(get_result_repo),
) -> ResultListOut:
    """분석 결과 목록 (FR-015, FR-016).

    기본적으로 무관·검증실패 항목은 빼고 준다. 사용자가 먼저 봐야 하는 것은
    ACTION/DECISION이고, 무관 항목은 요청해야 보이는 게 맞다.
    """
    analysis = await analysis_repo.get(analysis_id, user.user_id)
    if analysis is None:
        raise NotFoundError("분석을 찾을 수 없습니다.")

    results = await result_repo.list_for_analysis(analysis_id, user.user_id)

    visible = [
        r
        for r in results
        if (include_rejected or r.is_displayable)
        and (include_not_applicable or r.applicability is not Applicability.NOT_APPLICABLE)
    ]
    visible.sort(key=dashboard_order)

    return ResultListOut(
        analysis_id=analysis_id,
        status=analysis.status,
        counts=CountsOut.of(analysis.counts),
        items=[ResultOut.of(r) for r in visible],
    )


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_analysis(
    analysis_id: str,
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryAnalysisRepository = Depends(get_analysis_repo),
) -> None:
    """진행 중인 분석을 실패로 표시한다. 멈춘 분석이 새 실행을 영구히 막는 것을 방지."""
    analysis = await repo.get(analysis_id, user.user_id)
    if analysis is None:
        raise NotFoundError("분석을 찾을 수 없습니다.")
    if analysis.is_active:
        await repo.update(
            analysis.model_copy(
                update={
                    "status": AnalysisStatus.FAILED,
                    "completed_at": datetime.now(UTC),
                    "error": "사용자가 분석을 취소했습니다.",
                }
            )
        )
