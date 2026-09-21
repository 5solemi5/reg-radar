"""보류 재판정 (FR-008, BR-008).

보류는 '정보가 부족해 확정하지 못한 상태'다. 사용자가 부족한 정보를 채우면
**그 조문만** 다시 판단한다. 분석을 처음부터 다시 돌릴 이유가 없다.

BR-008: 기존 결과를 덮어쓰지 않고 새 결과를 만들어 이력으로 연결한다.
판정이 왜 바뀌었는지 추적할 수 없으면 사용자가 결과를 신뢰할 근거가 없다.

법령 원문은 law_snapshots에서 가져온다. 분석 당시 근거를 보존해 둔 이유가
이것이다 (AP-07) — 그 사이 법령이 또 개정됐더라도 같은 근거로 재판정한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai.chains.base import ChainRunner
from app.ai.llm import LlmGateway
from app.core.config import Settings, get_settings
from app.domain.context import ChangeContext, ContextPacket, UserContext
from app.domain.entities import HoldRevision, Profile
from app.domain.enums import Applicability
from app.domain.result import AnalysisResult
from app.services.analysis_service import analyze_article

logger = logging.getLogger(__name__)


class ReassessError(RuntimeError):
    """재판정을 수행할 수 없는 상태."""


class NotHoldError(ReassessError):
    """보류가 아닌 결과는 재판정 대상이 아니다."""


class SnapshotMissingError(ReassessError):
    """분석 당시 법령 근거가 없으면 재판정할 수 없다.

    없는 근거로 다시 판단하느니 실패를 드러내는 편이 낫다 (BR-001).
    """


@dataclass
class ReassessInput:
    """사용자가 채운 정보."""

    employee_count: int | None = None
    notes: str | None = None
    apply_to_profile: bool = False

    @property
    def is_empty(self) -> bool:
        return self.employee_count is None and not (self.notes or "").strip()

    def to_context_map(self) -> dict[str, str]:
        """이력에 남길 '무엇을 추가했는가'."""
        added: dict[str, str] = {}
        if self.employee_count is not None:
            added["상시근로자 수"] = str(self.employee_count)
        if self.notes and self.notes.strip():
            added["추가 설명"] = self.notes.strip()
        return added


@dataclass
class ReassessOutcome:
    result: AnalysisResult
    revision: HoldRevision
    changed: bool

    @property
    def summary(self) -> str:
        if not self.changed:
            return "추가 정보를 반영했지만 판정은 그대로입니다."
        return (
            f"{self.revision.previous_applicability.value} → "
            f"{self.revision.new_applicability.value}로 바뀌었습니다."
        )


def apply_overrides(profile: Profile, payload: ReassessInput) -> UserContext:
    """프로필에 추가 정보를 얹어 재판정용 컨텍스트를 만든다.

    프로필 자체를 바꾸지 않는 이유: 사용자가 '이 조문에 한해' 정보를 주는
    경우가 있고, 과거 분석은 당시 프로필 기준으로 보존되어야 하기 때문이다
    (FR-002 AC).
    """
    context = profile.to_user_context()
    updates: dict = {}
    if payload.employee_count is not None:
        updates["employee_count"] = payload.employee_count
    if payload.notes and payload.notes.strip():
        # 자유 서술은 직무 설명에 덧붙인다. 판정 근거에 반영되도록.
        updates["job"] = f"{context.job} · {payload.notes.strip()}"
    return context.model_copy(update=updates) if updates else context


class ReassessService:
    def __init__(
        self,
        *,
        snapshot_repo,
        result_repo,
        revision_repo,
        settings: Settings | None = None,
        llm_gateway: LlmGateway | None = None,
        retriever=None,
    ):
        self.snapshot_repo = snapshot_repo
        self.result_repo = result_repo
        self.revision_repo = revision_repo
        self.settings = settings or get_settings()
        self._llm = llm_gateway
        self._retriever = retriever

    @property
    def llm(self) -> LlmGateway:
        if self._llm is None:
            self._llm = LlmGateway(settings=self.settings)
        return self._llm

    async def _retrieve(self, legal, user):
        if self._retriever is None:
            return []
        try:
            return await self._retriever.retrieve(legal, user)
        except Exception as exc:
            # 참고자료는 없어도 재판정이 성립한다 (BR-005).
            logger.info("재판정 중 참고자료 검색 실패: %s", exc)
            return []

    async def reassess(
        self,
        *,
        original: AnalysisResult,
        profile: Profile,
        payload: ReassessInput,
        user_id: str,
    ) -> ReassessOutcome:
        if original.applicability is not Applicability.HOLD:
            raise NotHoldError("보류 상태인 결과만 재판정할 수 있습니다.")
        if payload.is_empty:
            raise ReassessError("추가 정보를 입력해야 재판정할 수 있습니다.")

        evidence = original.legal_evidence
        snapshot = await self.snapshot_repo.get(evidence.law_id)
        if snapshot is None:
            raise SnapshotMissingError(
                "분석 당시 법령 근거를 찾을 수 없어 재판정할 수 없습니다."
            )
        if snapshot.find_article(evidence.article_no) is None:
            raise SnapshotMissingError(
                f"{evidence.article_no}의 원문을 찾을 수 없습니다."
            )

        legal = snapshot.to_legal_context(evidence.article_no)
        user = apply_overrides(profile, payload)

        # 변경 내용은 최초 분석 때 저장해 둔 것을 그대로 쓴다. 신구법을 다시
        # 부르면 그 사이 또 개정됐을 때 다른 근거로 판단하게 된다 (BR-006).
        change = ChangeContext(
            change_type=original.change.change_type,
            additions=original.change.additions,
            deletions=original.change.deletions,
            delegation_targets=original.change.delegation_targets,
        )

        packet = ContextPacket(
            user=user,
            law=legal,
            change=change,
            rag=await self._retrieve(legal, user),
        )

        outcome = await analyze_article(
            ChainRunner(llm=self.llm),
            packet,
            analysis_id=original.analysis_id,
            trace_id=original.trace_id,
        )
        new_result = outcome.result

        await self.result_repo.save_many([new_result])
        revision = await self.revision_repo.create(
            HoldRevision(
                original_result_id=original.result_id,
                new_result_id=new_result.result_id,
                user_id=user_id,
                added_context=payload.to_context_map(),
                previous_applicability=original.applicability,
                new_applicability=new_result.applicability,
            )
        )

        return ReassessOutcome(
            result=new_result,
            revision=revision,
            changed=new_result.applicability is not original.applicability,
        )
