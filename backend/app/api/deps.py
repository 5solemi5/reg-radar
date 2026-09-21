"""의존성 컨테이너.

`STORAGE` 설정에 따라 인메모리와 Postgres 구현을 바꿔 끼운다. 라우터는 어느
쪽인지 모른다 — 저장소 Protocol만 알면 되기 때문이다 (NFR-011).

설정을 전역에서 직접 읽지 않고 `Depends(get_settings)`로 받는 이유: 그래야
`dependency_overrides`로 설정을 갈아끼울 수 있다. 전역을 읽으면 테스트가
개발자의 .env에 좌우되고, 실제로 .env를 postgres로 바꾸자 전체 테스트가
깨지는 일이 있었다.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.repositories.db import Database, get_database
from app.repositories.memory import (
    InMemoryAnalysisRepository,
    InMemoryFeedbackRepository,
    InMemoryProfileRepository,
    InMemoryResultRepository,
    InMemoryRevisionRepository,
    InMemorySavedRegulationRepository,
    InMemorySnapshotRepository,
    InMemoryStore,
)
from app.repositories.postgres import (
    PostgresAnalysisRepository,
    PostgresFeedbackRepository,
    PostgresProfileRepository,
    PostgresResultRepository,
    PostgresRevisionRepository,
    PostgresSavedRegulationRepository,
    PostgresSnapshotRepository,
)
from app.repositories.traces import (
    InMemoryTraceRepository,
    PostgresTraceRepository,
)


@lru_cache
def get_store() -> InMemoryStore:
    return InMemoryStore()


@lru_cache
def get_memory_trace_repo() -> InMemoryTraceRepository:
    return InMemoryTraceRepository()


def _db(settings: Settings) -> Database:
    return get_database(settings)


def get_profile_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresProfileRepository(_db(settings)) if settings.postgres_enabled
        else InMemoryProfileRepository(get_store())
    )


def get_analysis_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresAnalysisRepository(_db(settings)) if settings.postgres_enabled
        else InMemoryAnalysisRepository(get_store())
    )


def get_result_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresResultRepository(_db(settings)) if settings.postgres_enabled
        else InMemoryResultRepository(get_store())
    )


def get_snapshot_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresSnapshotRepository(_db(settings)) if settings.postgres_enabled
        else InMemorySnapshotRepository(get_store())
    )


def get_feedback_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresFeedbackRepository(_db(settings)) if settings.postgres_enabled
        else InMemoryFeedbackRepository(get_store())
    )


def get_saved_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresSavedRegulationRepository(_db(settings)) if settings.postgres_enabled
        else InMemorySavedRegulationRepository(get_store())
    )


def get_revision_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresRevisionRepository(_db(settings)) if settings.postgres_enabled
        else InMemoryRevisionRepository(get_store())
    )


def get_trace_repo(settings: Settings = Depends(get_settings)):
    return (
        PostgresTraceRepository(_db(settings)) if settings.postgres_enabled
        else get_memory_trace_repo()
    )


def get_analysis_runner(
    settings: Settings = Depends(get_settings),
    analysis_repo=Depends(get_analysis_repo),
    result_repo=Depends(get_result_repo),
    snapshot_repo=Depends(get_snapshot_repo),
    trace_repo=Depends(get_trace_repo),
):
    """분석 실행기.

    라우터가 이 함수에 의존하므로, 테스트는 dependency_overrides로 네트워크와
    LLM을 타지 않는 구현으로 갈아끼울 수 있다.
    """
    from app.services.analysis_runner import AnalysisRunner

    return AnalysisRunner(
        analysis_repo=analysis_repo,
        result_repo=result_repo,
        snapshot_repo=snapshot_repo,
        settings=settings,
        trace_repo=trace_repo,
    )


def get_retriever(settings: Settings = Depends(get_settings)):
    """참고자료 검색기. 구성 실패는 참고자료 없음으로 흡수한다 (BR-005)."""
    from app.rag.retriever import NullRetriever

    if not settings.rag_enabled:
        return NullRetriever()
    try:
        from app.rag.embeddings import OpenAIEmbedder
        from app.rag.retriever import Retriever
        from app.rag.store import build_store

        return Retriever(
            OpenAIEmbedder(settings), build_store(settings), top_k=settings.rag_top_k
        )
    except Exception:
        return NullRetriever()


def get_reassess_service(
    settings: Settings = Depends(get_settings),
    snapshot_repo=Depends(get_snapshot_repo),
    result_repo=Depends(get_result_repo),
    revision_repo=Depends(get_revision_repo),
    retriever=Depends(get_retriever),
):
    from app.services.reassess_service import ReassessService

    return ReassessService(
        snapshot_repo=snapshot_repo,
        result_repo=result_repo,
        revision_repo=revision_repo,
        settings=settings,
        retriever=retriever,
    )
