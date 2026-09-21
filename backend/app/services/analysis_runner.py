"""분석 실행 orchestration (04 설계서 §5-2, FR-003~FR-010).

흐름
  1. 프로필 확보 (없으면 실행 거부 — ER-006)
  2. 법제처에서 대상 법령 조회 (시행일 범위 또는 법령명)
  3. 법령별 신구법 비교 → **실제 변경된 조문만** 후보로 확보
  4. 조문별 AI 파이프라인(C3~C6) 실행
  5. snapshot·결과 저장, 집계 갱신, 상태 전이

실패 정책 (NFR-005): 어떤 실패도 성공으로 위장하지 않는다. 다만 법령 1건이
실패했다고 분석 전체를 버리지는 않는다. 부분 성공은 집계에 그대로 드러난다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from app.adapters.law.client import LawApiClient, LawApiError
from app.adapters.law.models import LawSnapshot, LawSummary
from app.adapters.law.oldnew import ChangedArticle
from app.ai.chains.base import ChainRunner
from app.ai.llm import LlmGateway
from app.core.config import Settings, get_settings
from app.diff.engine import change_from_official_marks
from app.domain.context import ContextPacket
from app.domain.entities import Analysis, Profile, ResultCounts
from app.domain.enums import ActionGrade, AnalysisStatus, Applicability, ResultStatus
from app.domain.result import AnalysisResult
from app.repositories.base import (
    AnalysisRepository,
    ResultRepository,
    SnapshotRepository,
)
from app.services.analysis_service import analyze_article

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 180
MAX_ARTICLES_PER_LAW = 10


def summarize(results: list[AnalysisResult]) -> ResultCounts:
    """대시보드 집계 (FR-015).

    BR-007에 따라 판정 축과 행동 축이 섞이지 않도록, 확정 판정만 행동 등급으로
    센다. 보류·무관·거부는 각자의 칸으로 간다.
    """
    counts = {
        "action": 0, "decision": 0, "awareness": 0,
        "hold": 0, "not_applicable": 0, "rejected": 0,
    }
    for r in results:
        if r.status is ResultStatus.REJECTED:
            counts["rejected"] += 1
        elif r.applicability is Applicability.HOLD:
            counts["hold"] += 1
        elif r.applicability is Applicability.NOT_APPLICABLE:
            counts["not_applicable"] += 1
        elif r.action_grade is ActionGrade.ACTION:
            counts["action"] += 1
        elif r.action_grade is ActionGrade.DECISION:
            counts["decision"] += 1
        else:
            counts["awareness"] += 1
    return ResultCounts(**counts)


@dataclass
class LawWorkItem:
    """법령 1건에서 뽑아낸 분석 대상."""

    summary: LawSummary
    snapshot: LawSnapshot
    changed: list[ChangedArticle] = field(default_factory=list)


class AnalysisRunner:
    def __init__(
        self,
        *,
        analysis_repo: AnalysisRepository,
        result_repo: ResultRepository,
        snapshot_repo: SnapshotRepository,
        settings: Settings | None = None,
        llm_gateway: LlmGateway | None = None,
        client_factory=None,
    ):
        self.analysis_repo = analysis_repo
        self.result_repo = result_repo
        self.snapshot_repo = snapshot_repo
        self.settings = settings or get_settings()
        self.llm = llm_gateway or LlmGateway(settings=self.settings)
        self._client_factory = client_factory or (
            lambda: LawApiClient(settings=self.settings)
        )

    # ── 법령 수집 ─────────────────────────────────────────────────────

    async def collect(self, analysis: Analysis, *, max_laws: int) -> list[LawWorkItem]:
        """분석 대상 법령과 '실제 변경된 조문'을 모은다 (FR-004, FR-005)."""
        items: list[LawWorkItem] = []
        async with self._client_factory() as client:
            if analysis.law_query:
                found = await client.search_laws(query=analysis.law_query, display=max_laws)
                laws = [law for law in found if law.law_name == analysis.law_query] or found
            else:
                start = analysis.period_from or (
                    date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
                )
                laws = await client.search_laws(
                    effective_from=start,
                    effective_to=analysis.period_to or date.today(),
                    display=max_laws,
                )

            for law in laws[:max_laws]:
                try:
                    comparison = await client.fetch_old_and_new(law)
                except LawApiError as exc:
                    # 신구법 비교가 없는 법령(제정 직후 등)도 있다. 건너뛰되 기록한다.
                    logger.info("신구법 비교 실패 law=%s: %s", law.law_name, exc)
                    continue

                if not comparison.changed_articles:
                    continue

                try:
                    snapshot = await client.fetch_law_detail(law)
                except LawApiError as exc:
                    logger.warning("본문 조회 실패 law=%s: %s", law.law_name, exc)
                    continue

                items.append(
                    LawWorkItem(
                        summary=law,
                        snapshot=snapshot,
                        changed=comparison.changed_articles[:MAX_ARTICLES_PER_LAW],
                    )
                )
        return items

    # ── 조문 분석 ─────────────────────────────────────────────────────

    async def analyze_item(
        self, item: LawWorkItem, profile: Profile, analysis: Analysis
    ) -> list[AnalysisResult]:
        user_context = profile.to_user_context()
        results: list[AnalysisResult] = []

        for changed in item.changed:
            article = item.snapshot.find_article(changed.article_no)
            if article is None:
                # 신구법에는 있는데 현행 본문에 없다 → 근거를 만들 수 없으므로 건너뛴다.
                logger.info(
                    "현행 본문에 없는 조문 건너뜀 law=%s article=%s",
                    item.snapshot.law_name, changed.article_no,
                )
                continue

            packet = ContextPacket(
                user=user_context,
                law=item.snapshot.to_legal_context(changed.article_no),
                change=change_from_official_marks(
                    before_text=changed.old_text,
                    after_text=changed.new_text,
                    additions=changed.additions,
                    deletions=changed.deletions,
                ),
                rag=[],  # W5에서 Retriever 연결
            )

            try:
                outcome = await analyze_article(
                    ChainRunner(llm=self.llm),
                    packet,
                    analysis_id=analysis.analysis_id,
                    trace_id=analysis.trace_id,
                )
            except Exception as exc:
                # ER-002/ER-003: 조문 1건 실패가 분석 전체를 죽이지 않는다.
                logger.warning(
                    "조문 분석 실패 law=%s article=%s err=%s",
                    item.snapshot.law_name, changed.article_no, exc,
                )
                continue

            results.append(outcome.result)
        return results

    # ── 실행 ──────────────────────────────────────────────────────────

    async def run(self, analysis: Analysis, profile: Profile, *, max_laws: int = 3) -> Analysis:
        analysis = analysis.model_copy(
            update={"status": AnalysisStatus.RUNNING, "started_at": datetime.now(UTC)}
        )
        await self.analysis_repo.update(analysis)

        try:
            items = await self.collect(analysis, max_laws=max_laws)
        except LawApiError as exc:
            logger.warning("법령 수집 실패 analysis=%s: %s", analysis.analysis_id, exc)
            return await self.fail(
                analysis, "법령 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."
            )
        except Exception as exc:
            logger.exception("법령 수집 중 예기치 못한 오류 analysis=%s", analysis.analysis_id)
            return await self.fail(analysis, "분석을 준비하지 못했습니다.", detail=str(exc))

        all_results: list[AnalysisResult] = []
        for item in items:
            await self.snapshot_repo.save(item.snapshot)
            all_results.extend(await self.analyze_item(item, profile, analysis))

        await self.result_repo.save_many(all_results)

        completed = analysis.model_copy(
            update={
                "status": AnalysisStatus.COMPLETED,
                "completed_at": datetime.now(UTC),
                "laws_examined": len(items),
                "articles_changed": sum(len(i.changed) for i in items),
                "counts": summarize(all_results),
                "snapshot_law_ids": [i.snapshot.law_id for i in items],
            }
        )
        return await self.analysis_repo.update(completed)

    async def fail(
        self, analysis: Analysis, message: str, *, detail: str | None = None
    ) -> Analysis:
        if detail:
            logger.info("분석 실패 상세 analysis=%s: %s", analysis.analysis_id, detail)
        failed = analysis.model_copy(
            update={
                "status": AnalysisStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "error": message,
            }
        )
        return await self.analysis_repo.update(failed)
