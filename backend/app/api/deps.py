"""의존성 컨테이너.

`STORAGE` 설정에 따라 인메모리와 Postgres 구현을 바꿔 끼운다. 라우터는 어느
쪽인지 모른다 — 저장소 Protocol만 알면 되기 때문이다 (NFR-011).
"""

from __future__ import annotations

from functools import lru_cache

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


@lru_cache
def get_store() -> InMemoryStore:
    return InMemoryStore()


def _use_postgres(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).postgres_enabled


def _db() -> Database:
    return get_database()


def get_profile_repo():
    return (
        PostgresProfileRepository(_db()) if _use_postgres()
        else InMemoryProfileRepository(get_store())
    )


def get_analysis_repo():
    return (
        PostgresAnalysisRepository(_db()) if _use_postgres()
        else InMemoryAnalysisRepository(get_store())
    )


def get_result_repo():
    return (
        PostgresResultRepository(_db()) if _use_postgres()
        else InMemoryResultRepository(get_store())
    )


def get_snapshot_repo():
    return (
        PostgresSnapshotRepository(_db()) if _use_postgres()
        else InMemorySnapshotRepository(get_store())
    )


def get_feedback_repo():
    return (
        PostgresFeedbackRepository(_db()) if _use_postgres()
        else InMemoryFeedbackRepository(get_store())
    )


def get_saved_repo():
    return (
        PostgresSavedRegulationRepository(_db()) if _use_postgres()
        else InMemorySavedRegulationRepository(get_store())
    )


def get_revision_repo():
    return (
        PostgresRevisionRepository(_db()) if _use_postgres()
        else InMemoryRevisionRepository(get_store())
    )


def get_analysis_runner():
    """분석 실행기.

    라우터가 이 함수에 의존하므로, 테스트는 dependency_overrides로 네트워크와
    LLM을 타지 않는 구현으로 갈아끼울 수 있다.
    """
    from app.services.analysis_runner import AnalysisRunner

    return AnalysisRunner(
        analysis_repo=get_analysis_repo(),
        result_repo=get_result_repo(),
        snapshot_repo=get_snapshot_repo(),
        settings=get_settings(),
    )
