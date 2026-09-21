"""의존성 컨테이너.

인메모리 repository는 앱 수명 동안 유지되는 단일 store를 공유한다.
W3에서 Supabase 구현으로 바꿀 때 이 모듈만 고치면 된다.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
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


@lru_cache
def get_store() -> InMemoryStore:
    return InMemoryStore()


def get_profile_repo() -> InMemoryProfileRepository:
    return InMemoryProfileRepository(get_store())


def get_analysis_repo() -> InMemoryAnalysisRepository:
    return InMemoryAnalysisRepository(get_store())


def get_result_repo() -> InMemoryResultRepository:
    return InMemoryResultRepository(get_store())


def get_snapshot_repo() -> InMemorySnapshotRepository:
    return InMemorySnapshotRepository(get_store())


def get_feedback_repo() -> InMemoryFeedbackRepository:
    return InMemoryFeedbackRepository(get_store())


def get_saved_repo() -> InMemorySavedRegulationRepository:
    return InMemorySavedRegulationRepository(get_store())


def get_revision_repo() -> InMemoryRevisionRepository:
    return InMemoryRevisionRepository(get_store())


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
