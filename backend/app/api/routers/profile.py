"""프로필 API (FR-002, UC-01)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status

from app.api.auth import CurrentUser, get_current_user
from app.api.deps import get_profile_repo
from app.api.errors import ErrorResponse, NotFoundError
from app.api.schemas import ProfileIn, ProfileOut, ProfilePatch
from app.domain.entities import Profile
from app.repositories.memory import InMemoryProfileRepository

router = APIRouter(tags=["profile"])


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
