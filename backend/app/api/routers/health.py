"""헬스 체크 — 배포 환경에서 외부 의존성 설정 여부를 확인한다."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


class HealthOut(BaseModel):
    status: str
    env: str
    auth_mode: str
    storage: str
    database_connected: bool
    rag_enabled: bool = Field(..., description="설정 플래그(RAG_ENABLED)")
    rag_operational: bool = Field(
        ..., description="실제로 참고자료 검색이 가능한 상태인지. 플래그와 별개다."
    )
    rag_indexed_chunks: int
    rag_error: str | None = Field(
        None, description="RAG를 쓸 수 없는 이유. 정상이거나 꺼져 있으면 null."
    )
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
    #
    # '청크 0건'만으로는 원인을 가릴 수 없다는 것이 배포 검증에서 드러났다.
    # 인덱스가 빈 것과 chromadb가 아예 없는 것이 똑같이 0으로 보였고, 운영자는
    # 적재만 하면 된다고 오해하게 된다. 그래서 동작 가능 여부와 이유를 나눈다.
    indexed = 0
    operational = False
    rag_error: str | None = None
    if settings.rag_enabled:
        try:
            from app.rag.store import build_store

            indexed = await build_store(settings).count()
            operational = True
        except Exception as exc:  # 진단용이므로 예외 종류를 가리지 않는다
            # 키나 접속 문자열이 섞여 나가지 않도록 타입과 짧은 메시지만 남긴다 (NFR-008).
            rag_error = f"{type(exc).__name__}: {exc}"[:200]
    return HealthOut(
        status="ok",
        env=settings.app_env,
        auth_mode=settings.auth_mode,
        storage=settings.storage,
        database_connected=connected,
        rag_enabled=settings.rag_enabled,
        rag_operational=operational,
        rag_indexed_chunks=indexed,
        rag_error=rag_error,
        law_api_configured=settings.law_api_enabled,
        llm_configured=settings.llm_enabled,
        llm_model=settings.llm_model,
    )
