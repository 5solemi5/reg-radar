"""결과 상세·근거·피드백·저장 API (FR-012~014, FR-017, FR-019)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.auth import CurrentUser, get_current_user
from app.api.deps import get_feedback_repo, get_result_repo, get_saved_repo
from app.api.errors import ErrorResponse, NotFoundError
from app.api.schemas import (
    EvidenceOut,
    FeedbackIn,
    FeedbackOut,
    ResultOut,
    SavedRegulationIn,
    SavedRegulationOut,
)
from app.domain.entities import Feedback, SavedRegulation
from app.repositories.memory import (
    InMemoryFeedbackRepository,
    InMemoryResultRepository,
    InMemorySavedRegulationRepository,
)

router = APIRouter(tags=["results"])


@router.get(
    "/results/{result_id}",
    response_model=ResultOut,
    responses={404: {"model": ErrorResponse}},
)
async def get_result(
    result_id: str,
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryResultRepository = Depends(get_result_repo),
) -> ResultOut:
    """규제 상세 (FR-016)."""
    result = await repo.get(result_id, user.user_id)
    if result is None:
        raise NotFoundError("결과를 찾을 수 없습니다.")
    return ResultOut.of(result)


@router.get(
    "/results/{result_id}/evidence",
    response_model=EvidenceOut,
    responses={404: {"model": ErrorResponse}},
)
async def get_evidence(
    result_id: str,
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryResultRepository = Depends(get_result_repo),
) -> EvidenceOut:
    """근거 조회 (FR-012, FR-013, FR-014).

    세 근거를 **별도 키**로 내보낸다. 프론트가 실수로 섞어 렌더링하려면
    의도적으로 합쳐야 하고, 응답만 봐도 무엇이 공식 원문이고 무엇이 AI 해석인지
    구분된다 (AP-05).
    """
    result = await repo.get(result_id, user.user_id)
    if result is None:
        raise NotFoundError("결과를 찾을 수 없습니다.")

    full = ResultOut.of(result)
    return EvidenceOut(
        result_id=result.result_id,
        legal_evidence=full.legal_evidence,
        reference_evidence=full.reference_evidence,
        ai_interpretation=full.ai_interpretation,
    )


@router.post(
    "/results/{result_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}},
)
async def submit_feedback(
    result_id: str,
    payload: FeedbackIn,
    user: CurrentUser = Depends(get_current_user),
    result_repo: InMemoryResultRepository = Depends(get_result_repo),
    feedback_repo: InMemoryFeedbackRepository = Depends(get_feedback_repo),
) -> FeedbackOut:
    """AI 판정에 대한 유용성/오류 피드백 (FR-019)."""
    if await result_repo.get(result_id, user.user_id) is None:
        raise NotFoundError("결과를 찾을 수 없습니다.")

    saved = await feedback_repo.create(
        Feedback(result_id=result_id, user_id=user.user_id, **payload.model_dump())
    )
    return FeedbackOut(**saved.model_dump(exclude={"user_id"}))


@router.post(
    "/saved-regulations",
    response_model=SavedRegulationOut,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}},
)
async def save_regulation(
    payload: SavedRegulationIn,
    user: CurrentUser = Depends(get_current_user),
    result_repo: InMemoryResultRepository = Depends(get_result_repo),
    saved_repo: InMemorySavedRegulationRepository = Depends(get_saved_repo),
) -> SavedRegulationOut:
    """관심 규제 저장 (FR-017)."""
    result = await result_repo.get(payload.result_id, user.user_id)
    if result is None:
        raise NotFoundError("결과를 찾을 수 없습니다.")

    evidence = result.legal_evidence
    saved = await saved_repo.create(
        SavedRegulation(
            user_id=user.user_id,
            result_id=payload.result_id,
            law_id=evidence.law_id,
            law_name=evidence.law_name,
            article_no=evidence.article_no,
            note=payload.note,
        )
    )
    return SavedRegulationOut(**saved.model_dump(exclude={"user_id"}))


@router.get("/saved-regulations", response_model=list[SavedRegulationOut])
async def list_saved(
    user: CurrentUser = Depends(get_current_user),
    saved_repo: InMemorySavedRegulationRepository = Depends(get_saved_repo),
) -> list[SavedRegulationOut]:
    items = await saved_repo.list_for_user(user.user_id)
    return [SavedRegulationOut(**s.model_dump(exclude={"user_id"})) for s in items]


@router.delete("/saved-regulations/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved(
    saved_id: str,
    user: CurrentUser = Depends(get_current_user),
    saved_repo: InMemorySavedRegulationRepository = Depends(get_saved_repo),
) -> None:
    if not await saved_repo.delete(saved_id, user.user_id):
        raise NotFoundError("저장된 규제를 찾을 수 없습니다.")
