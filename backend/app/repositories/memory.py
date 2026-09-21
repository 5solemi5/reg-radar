"""인메모리 Repository 구현 (W2용).

프로세스가 죽으면 사라진다. W3에서 Supabase 구현으로 교체하는 것을 전제로 한다.
결과 소유권 확인은 analysis_id → user_id 역참조로 한다.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.adapters.law.models import LawSnapshot
from app.domain.entities import (
    Analysis,
    Feedback,
    HoldRevision,
    Profile,
    SavedRegulation,
)
from app.domain.result import AnalysisResult


class InMemoryStore:
    """모든 인메모리 repository가 공유하는 저장 공간."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.profiles: dict[str, Profile] = {}
        self.analyses: dict[str, Analysis] = {}
        self.results: dict[str, AnalysisResult] = {}
        self.result_owner: dict[str, str] = {}          # result_id → user_id
        self.results_by_analysis: dict[str, list[str]] = defaultdict(list)
        self.snapshots: dict[str, LawSnapshot] = {}
        self.feedback: dict[str, Feedback] = {}
        self.saved: dict[str, SavedRegulation] = {}
        self.revisions: dict[str, HoldRevision] = {}

    def clear(self) -> None:
        for attr in (
            "profiles", "analyses", "results", "result_owner",
            "snapshots", "feedback", "saved", "revisions",
        ):
            getattr(self, attr).clear()
        self.results_by_analysis.clear()


class InMemoryProfileRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get(self, user_id: str) -> Profile | None:
        return self._store.profiles.get(user_id)

    async def upsert(self, profile: Profile) -> Profile:
        async with self._store.lock:
            existing = self._store.profiles.get(profile.user_id)
            if existing is not None:
                profile = profile.model_copy(update={"created_at": existing.created_at})
            self._store.profiles[profile.user_id] = profile
        return profile


class InMemoryAnalysisRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(self, analysis: Analysis) -> Analysis:
        async with self._store.lock:
            self._store.analyses[analysis.analysis_id] = analysis
        return analysis

    async def get(self, analysis_id: str, user_id: str) -> Analysis | None:
        analysis = self._store.analyses.get(analysis_id)
        # NFR-007: 남의 분석은 '없는 것'으로 보인다. 존재 여부도 알려주지 않는다.
        return analysis if analysis and analysis.user_id == user_id else None

    async def update(self, analysis: Analysis) -> Analysis:
        async with self._store.lock:
            self._store.analyses[analysis.analysis_id] = analysis
        return analysis

    async def list_for_user(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[Analysis], int]:
        owned = [a for a in self._store.analyses.values() if a.user_id == user_id]
        owned.sort(key=lambda a: a.created_at, reverse=True)
        return owned[offset : offset + limit], len(owned)

    async def find_active(self, user_id: str) -> Analysis | None:
        return next(
            (
                a
                for a in sorted(
                    self._store.analyses.values(), key=lambda x: x.created_at, reverse=True
                )
                if a.user_id == user_id and a.is_active
            ),
            None,
        )


class InMemoryResultRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def save_many(self, results: list[AnalysisResult]) -> None:
        async with self._store.lock:
            for result in results:
                self._store.results[result.result_id] = result
                if result.analysis_id:
                    analysis = self._store.analyses.get(result.analysis_id)
                    if analysis:
                        self._store.result_owner[result.result_id] = analysis.user_id
                    if result.result_id not in self._store.results_by_analysis[result.analysis_id]:
                        self._store.results_by_analysis[result.analysis_id].append(
                            result.result_id
                        )

    async def get(self, result_id: str, user_id: str) -> AnalysisResult | None:
        if self._store.result_owner.get(result_id) != user_id:
            return None
        return self._store.results.get(result_id)

    async def list_for_analysis(
        self, analysis_id: str, user_id: str
    ) -> list[AnalysisResult]:
        analysis = self._store.analyses.get(analysis_id)
        if analysis is None or analysis.user_id != user_id:
            return []
        return [
            self._store.results[rid]
            for rid in self._store.results_by_analysis.get(analysis_id, [])
            if rid in self._store.results
        ]


class InMemorySnapshotRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def save(self, snapshot: LawSnapshot) -> None:
        async with self._store.lock:
            self._store.snapshots[snapshot.law_id] = snapshot

    async def get(self, law_id: str) -> LawSnapshot | None:
        return self._store.snapshots.get(law_id)


class InMemoryFeedbackRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(self, feedback: Feedback) -> Feedback:
        async with self._store.lock:
            self._store.feedback[feedback.feedback_id] = feedback
        return feedback

    async def list_for_result(self, result_id: str, user_id: str) -> list[Feedback]:
        return [
            f
            for f in self._store.feedback.values()
            if f.result_id == result_id and f.user_id == user_id
        ]


class InMemorySavedRegulationRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(self, saved: SavedRegulation) -> SavedRegulation:
        async with self._store.lock:
            self._store.saved[saved.saved_id] = saved
        return saved

    async def list_for_user(self, user_id: str) -> list[SavedRegulation]:
        items = [s for s in self._store.saved.values() if s.user_id == user_id]
        items.sort(key=lambda s: s.created_at, reverse=True)
        return items

    async def delete(self, saved_id: str, user_id: str) -> bool:
        async with self._store.lock:
            item = self._store.saved.get(saved_id)
            if item is None or item.user_id != user_id:
                return False
            del self._store.saved[saved_id]
        return True


class InMemoryRevisionRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(self, revision: HoldRevision) -> HoldRevision:
        async with self._store.lock:
            self._store.revisions[revision.revision_id] = revision
        return revision

    async def list_for_result(self, result_id: str, user_id: str) -> list[HoldRevision]:
        return [
            r
            for r in self._store.revisions.values()
            if r.user_id == user_id
            and result_id in (r.original_result_id, r.new_result_id)
        ]
