"""Repository 인터페이스 (NFR-011).

W2에서는 인메모리 구현을 쓰고 W3에서 Supabase 구현으로 교체한다.
서비스 계층은 이 Protocol만 알면 되므로 교체가 비즈니스 로직으로 번지지 않는다.

NFR-007(데이터 격리): 사용자 데이터를 다루는 모든 조회는 user_id를 **필수 인자로**
받는다. 호출자가 깜빡하면 컴파일 단계에서 드러나지, 런타임에 남의 데이터가
새는 방식으로는 틀릴 수 없게 만든다.
"""

from __future__ import annotations

from typing import Protocol

from app.adapters.law.models import LawSnapshot
from app.domain.entities import (
    Analysis,
    Feedback,
    HoldRevision,
    Profile,
    SavedRegulation,
)
from app.domain.result import AnalysisResult


class ProfileRepository(Protocol):
    async def get(self, user_id: str) -> Profile | None: ...
    async def upsert(self, profile: Profile) -> Profile: ...


class AnalysisRepository(Protocol):
    async def create(self, analysis: Analysis) -> Analysis: ...
    async def get(self, analysis_id: str, user_id: str) -> Analysis | None: ...
    async def update(self, analysis: Analysis) -> Analysis: ...
    async def list_for_user(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[Analysis], int]: ...
    async def find_active(self, user_id: str) -> Analysis | None: ...


class ResultRepository(Protocol):
    async def save_many(self, results: list[AnalysisResult]) -> None: ...
    async def get(self, result_id: str, user_id: str) -> AnalysisResult | None: ...
    async def list_for_analysis(
        self, analysis_id: str, user_id: str
    ) -> list[AnalysisResult]: ...


class SnapshotRepository(Protocol):
    async def save(self, snapshot: LawSnapshot) -> None: ...
    async def get(self, law_id: str) -> LawSnapshot | None: ...


class FeedbackRepository(Protocol):
    async def create(self, feedback: Feedback) -> Feedback: ...
    async def list_for_result(self, result_id: str, user_id: str) -> list[Feedback]: ...


class SavedRegulationRepository(Protocol):
    async def create(self, saved: SavedRegulation) -> SavedRegulation: ...
    async def list_for_user(self, user_id: str) -> list[SavedRegulation]: ...
    async def delete(self, saved_id: str, user_id: str) -> bool: ...


class RevisionRepository(Protocol):
    async def create(self, revision: HoldRevision) -> HoldRevision: ...
    async def list_for_result(self, result_id: str, user_id: str) -> list[HoldRevision]: ...
