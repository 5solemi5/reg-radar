"""헬스 체크 — 배포 환경에서 외부 의존성 설정 여부를 확인한다."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


class HealthOut(BaseModel):
    status: str
    env: str
    auth_mode: str
    law_api_configured: bool
    llm_configured: bool
    llm_model: str


@router.get("/health", response_model=HealthOut)
async def health(settings: Settings = Depends(get_settings)) -> HealthOut:
    """설정 상태만 보고한다. 키 값 자체는 절대 노출하지 않는다 (NFR-008)."""
    return HealthOut(
        status="ok",
        env=settings.app_env,
        auth_mode=settings.auth_mode,
        law_api_configured=settings.law_api_enabled,
        llm_configured=settings.llm_enabled,
        llm_model=settings.llm_model,
    )
