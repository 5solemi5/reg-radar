"""프로필 API (FR-002, UC-01)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status

from app.api.auth import CurrentUser, get_current_user
from app.api.deps import get_profile_repo
from app.api.errors import ErrorResponse, NotFoundError
from app.api.schemas import (
    ActivityQuestionListOut,
    ActivityQuestionOut,
    ProfileIn,
    ProfileOut,
    ProfilePatch,
)
from app.domain.activities import ACTIVITY_QUESTIONS
from app.domain.entities import Profile
from app.repositories.memory import InMemoryProfileRepository

router = APIRouter(tags=["profile"])


@router.get("/profile/activities", response_model=ActivityQuestionListOut)
async def list_activity_questions() -> ActivityQuestionListOut:
    """온보딩 화면이 그릴 사업 활동 질문 목록 (ADR-033).

    인증이 필요 없다. 어떤 질문을 하는지는 비밀이 아니고, 온보딩 화면이 프로필
    조회(404)와 이 목록을 함께 받아야 하는데 둘의 인증 상태를 맞출 이유가 없다.

    프론트엔드가 같은 문구를 따로 들고 있으면 반드시 어긋난다. 항목이 하나 빠져도
    아무도 모르고, 사용자는 답할 기회조차 없는 질문 때문에 보류를 받는다.
    """
    return ActivityQuestionListOut(
        items=[ActivityQuestionOut(**q.model_dump()) for q in ACTIVITY_QUESTIONS]
    )


@router.get(
    "/profile",
    response_model=ProfileOut,
    responses={404: {"model": ErrorResponse, "description": "프로필 미설정 — 온보딩 필요"}},
)
async def get_profile(
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryProfileRepository = Depends(get_profile_repo),
) -> ProfileOut:
    """현재 사용자의 업무 프로필.

    프로필이 없으면 404다. 프론트는 이 신호로 온보딩을 먼저 띄운다 (FR-002 AC).
    """
    profile = await repo.get(user.user_id)
    if profile is None:
        raise NotFoundError("프로필이 아직 설정되지 않았습니다.")
    return ProfileOut.of(profile)


@router.put("/profile", response_model=ProfileOut, status_code=status.HTTP_200_OK)
async def put_profile(
    payload: ProfileIn,
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryProfileRepository = Depends(get_profile_repo),
) -> ProfileOut:
    """프로필 생성 또는 전체 교체."""
    saved = await repo.upsert(
        Profile(user_id=user.user_id, **payload.model_dump(), updated_at=datetime.now(UTC))
    )
    return ProfileOut.of(saved)


@router.patch("/profile", response_model=ProfileOut)
async def patch_profile(
    payload: ProfilePatch,
    user: CurrentUser = Depends(get_current_user),
    repo: InMemoryProfileRepository = Depends(get_profile_repo),
) -> ProfileOut:
    """부분 수정.

    FR-002 AC: 프로필이 바뀌어도 기존 분석 이력은 당시 기준으로 보존된다.
    여기서는 프로필만 갱신하고 과거 결과는 건드리지 않는다.
    """
    current = await repo.get(user.user_id)
    if current is None:
        raise NotFoundError("먼저 프로필을 생성해야 합니다.")

    changes = payload.model_dump(exclude_unset=True)
    updated = await repo.upsert(
        current.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
    )
    return ProfileOut.of(updated)
