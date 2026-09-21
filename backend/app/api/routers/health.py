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
    storage: str
    database_connected: bool
    rag_enabled: bool
    rag_indexed_chunks: int
    law_api_configured: bool
    llm_configured: bool
    llm_model: str


@router.get("/health", response_model=HealthOut)
async def health(settings: Settings = Depends(get_settings)) -> HealthOut:
    """설정 상태만 보고한다. 키 값 자체는 절대 노출하지 않는다 (NFR-008)."""
    from app.repositories.db import get_database

    connected = settings.postgres_enabled and get_database(settings).is_connected

    # 인덱스가 비어 있으면 참고자료가 항상 0건이 된다. 설정 실수를 알아챌 수
    # 있도록 노출한다 (BR-005는 0건을 정상으로 처리하므로 조용히 묻힌다).
    indexed = 0
    if settings.rag_enabled:
        try:
            from app.rag.store import build_store

            indexed = await build_store(settings).count()
        except Exception:
            indexed = 0
    return HealthOut(
        status="ok",
        env=settings.app_env,
        auth_mode=settings.auth_mode,
        storage=settings.storage,
        database_connected=connected,
        rag_enabled=settings.rag_enabled,
        rag_indexed_chunks=indexed,
        law_api_configured=settings.law_api_enabled,
        llm_configured=settings.llm_enabled,
        llm_model=settings.llm_model,
    )
