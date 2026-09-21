"""결과 상세·근거·피드백·저장 API (FR-012~014, FR-017, FR-019)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.auth import CurrentUser, get_current_user
from app.api.deps import (
    get_feedback_repo,
    get_profile_repo,
    get_reassess_service,
    get_result_repo,
    get_revision_repo,
    get_saved_repo,
)
from app.api.errors import (
    ErrorResponse,
    NotFoundError,
    ProfileRequiredError,
    ReassessNotAllowedError,
)
from app.api.schemas import (
    EvidenceOut,
    FeedbackIn,
    FeedbackOut,
    ReassessIn,
    ReassessOut,
    ResultOut,
    RevisionOut,
    SavedRegulationIn,
    SavedRegulationOut,
)
from app.domain.entities import Feedback, SavedRegulation
from app.repositories.memory import (
    InMemoryFeedbackRepository,
    InMemoryResultRepository,
    InMemorySavedRegulationRepository,
)
from app.services.reassess_service import (
    ReassessError,
    ReassessInput,
    ReassessService,
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


@router.post(
    "/results/{result_id}/reassess",
    response_model=ReassessOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "보류 상태가 아니거나 근거 없음"},
    },
)
async def reassess_result(
    result_id: str,
    payload: ReassessIn,
    user: CurrentUser = Depends(get_current_user),
    result_repo: InMemoryResultRepository = Depends(get_result_repo),
    profile_repo=Depends(get_profile_repo),
    service: ReassessService = Depends(get_reassess_service),
) -> ReassessOut:
    """보류 결과를 추가 정보로 다시 판단한다 (FR-008).

    **기존 결과를 덮어쓰지 않는다.** 새 결과를 만들고 이력으로 연결하므로
    판정이 왜 바뀌었는지 추적할 수 있다 (BR-008).

    해당 조문 하나만 다시 판단한다. 분석 전체를 다시 돌릴 이유가 없다.
    """
    original = await result_repo.get(result_id, user.user_id)
    if original is None:
        raise NotFoundError("결과를 찾을 수 없습니다.")

    profile = await profile_repo.get(user.user_id)
    if profile is None:
        raise ProfileRequiredError()

    reassess_input = ReassessInput(
        employee_count=payload.employee_count,
        notes=payload.notes,
        apply_to_profile=payload.apply_to_profile,
    )

    try:
        outcome = await service.reassess(
            original=original,
            profile=profile,
            payload=reassess_input,
            user_id=user.user_id,
        )
    except ReassessError as exc:
        raise ReassessNotAllowedError(str(exc)) from exc

    # 프로필 반영은 재판정이 성공한 뒤에 한다. 실패했는데 프로필만 바뀌면
    # 사용자가 무엇이 적용됐는지 알 수 없다.
    if payload.apply_to_profile and payload.employee_count is not None:
        await profile_repo.upsert(
            profile.model_copy(update={"employee_count": payload.employee_count})
        )

    return ReassessOut(
        revision_id=outcome.revision.revision_id,
        original_result_id=original.result_id,
        previous_applicability=outcome.revision.previous_applicability,
        new_applicability=outcome.revision.new_applicability,
        changed=outcome.changed,
        message=outcome.summary,
        added_context=outcome.revision.added_context,
        result=ResultOut.of(outcome.result),
    )


@router.get(
    "/results/{result_id}/revisions",
    response_model=list[RevisionOut],
    responses={404: {"model": ErrorResponse}},
)
async def list_revisions(
    result_id: str,
    user: CurrentUser = Depends(get_current_user),
    result_repo: InMemoryResultRepository = Depends(get_result_repo),
    revision_repo=Depends(get_revision_repo),
) -> list[RevisionOut]:
    """이 결과와 연결된 재판정 이력 (BR-008)."""
    if await result_repo.get(result_id, user.user_id) is None:
        raise NotFoundError("결과를 찾을 수 없습니다.")

    revisions = await revision_repo.list_for_result(result_id, user.user_id)
    return [
        RevisionOut(
            revision_id=r.revision_id,
            original_result_id=r.original_result_id,
            new_result_id=r.new_result_id,
            previous_applicability=r.previous_applicability,
            new_applicability=r.new_applicability,
            added_context=r.added_context,
            created_at=r.created_at,
        )
        for r in revisions
    ]
