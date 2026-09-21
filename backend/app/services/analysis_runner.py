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

import asyncio
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
from app.rag.retriever import NullRetriever
from app.repositories.base import (
    AnalysisRepository,
    ResultRepository,
    SnapshotRepository,
)
from app.repositories.traces import NullTraceRepository, TraceRecord
from app.services.analysis_service import analyze_article
from app.services.law_selector import build_search_keywords, dedupe_laws, pick_primary

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 180
MAX_ARTICLES_PER_LAW = 6
# 검색어가 많아도 법제처 호출 횟수를 제한한다.
MAX_SEARCH_KEYWORDS = 8
# 분석 1회의 총 조문 수 상한. 조문 1건이 LLM 3회(C3~C5)를 쓰므로 상한이 없으면
# 개정 범위가 넓은 법령 하나만 걸려도 분석이 수 분씩 걸린다 (NFR-006).
MAX_ARTICLES_PER_ANALYSIS = 12
# 조문 분석 동시 실행 수. 순차로 돌리면 사용자가 기다리는 시간이 조문 수에
# 비례해 늘어난다. 모델 rate limit을 고려해 과하지 않게 잡는다.
ARTICLE_CONCURRENCY = 4


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
        retriever=None,
        trace_repo=None,
    ):
        self.analysis_repo = analysis_repo
        self.result_repo = result_repo
        self.snapshot_repo = snapshot_repo
        self.settings = settings or get_settings()
        self.llm = llm_gateway or LlmGateway(settings=self.settings)
        self._client_factory = client_factory or (
            lambda: LawApiClient(settings=self.settings)
        )
        # RAG가 꺼져 있거나 인덱스가 없으면 참고자료 없이 분석한다 (BR-005).
        self._retriever = retriever or self._build_retriever()
        self._trace_repo = trace_repo or NullTraceRepository()

    def _build_retriever(self):
        if not self.settings.rag_enabled:
            return NullRetriever()
        try:
            from app.rag.embeddings import OpenAIEmbedder
            from app.rag.retriever import Retriever
            from app.rag.store import build_store

            return Retriever(
                OpenAIEmbedder(self.settings),
                build_store(self.settings),
                top_k=self.settings.rag_top_k,
            )
        except Exception as exc:
            # 참고자료는 없어도 분석이 성립한다. 구성 실패로 분석을 막지 않는다.
            logger.warning("RAG 구성 실패 — 참고자료 없이 동작합니다: %s", exc)
            return NullRetriever()

    # ── 법령 수집 ─────────────────────────────────────────────────────

    async def select_laws(
        self, client, analysis: Analysis, profile: Profile, *, max_laws: int
    ) -> list[LawSummary]:
        """분석할 법령을 고른다.

        사용자가 법령을 지정했으면 그것만 본다. 아니면 프로필의 관심 영역·업종을
        검색어로 바꿔 후보를 좁힌다. 최신순으로 아무거나 집으면 무관한 법령만
        분석하게 된다 — 실측에서 IT HR 담당자에게 '감사원사무처 직제'가 나왔다.
        """
        if analysis.law_query:
            found = await client.search_laws(query=analysis.law_query, display=max_laws)
            exact = [law for law in found if law.law_name == analysis.law_query]
            return (exact or found)[:max_laws]

        start = analysis.period_from or (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS))
        end = analysis.period_to or date.today()

        keywords = build_search_keywords(
            interests=profile.interests, industry=profile.industry, job=profile.job
        )
        # 검색어마다 대표 법령 1건씩만 담는다. 시행령·시행규칙까지 담으면
        # 첫 검색어가 예산을 독식해 다른 관심 영역은 검색조차 되지 않는다.
        candidates: list[LawSummary] = []
        for keyword in keywords[:MAX_SEARCH_KEYWORDS]:
            if len(candidates) >= max_laws * 2:
                break
            try:
                found = await client.search_laws(query=keyword, display=5)
            except LawApiError as exc:
                logger.info("법령 검색 실패 keyword=%s: %s", keyword, exc)
                continue
            primary = pick_primary(found, keyword)
            if primary is not None:
                candidates.append(primary)

        # 기간 안에 시행되는 것을 우선한다. 없으면 검색 순서를 유지한다.
        unique = dedupe_laws(candidates)
        in_period = [
            law for law in unique
            if law.effective_date and start <= law.effective_date <= end
        ]
        selected = in_period or unique

        if not selected:
            # 프로필 기반 검색이 아무것도 못 찾으면 기간 내 최신 법령으로 되돌아간다.
            selected = await client.search_laws(
                effective_from=start, effective_to=end, display=max_laws
            )
        return selected[:max_laws]

    async def collect(
        self, analysis: Analysis, profile: Profile, *, max_laws: int
    ) -> list[LawWorkItem]:
        """분석 대상 법령과 '실제 변경된 조문'을 모은다 (FR-004, FR-005)."""
        items: list[LawWorkItem] = []
        async with self._client_factory() as client:
            laws = await self.select_laws(client, analysis, profile, max_laws=max_laws)

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

    async def build_packets(
        self, item: LawWorkItem, profile: Profile
    ) -> list[tuple[str, ContextPacket]]:
        """변경 조문을 AI 입력 packet으로 바꾼다. (조문번호, packet) 목록."""
        user_context = profile.to_user_context()
        packets: list[tuple[str, ContextPacket]] = []

        for changed in item.changed:
            if item.snapshot.find_article(changed.article_no) is None:
                # 신구법에는 있는데 현행 본문에 없다 → 근거를 만들 수 없으므로 건너뛴다.
                logger.info(
                    "현행 본문에 없는 조문 건너뜀 law=%s article=%s",
                    item.snapshot.law_name, changed.article_no,
                )
                continue

            legal = item.snapshot.to_legal_context(changed.article_no)
            # 참고자료 검색 실패는 빈 목록으로 흡수된다 (BR-005).
            rag = await self._retriever.retrieve(legal, user_context)

            packets.append((
                changed.article_no,
                ContextPacket(
                    user=user_context,
                    law=legal,
                    change=change_from_official_marks(
                        before_text=changed.old_text,
                        after_text=changed.new_text,
                        additions=changed.additions,
                        deletions=changed.deletions,
                    ),
                    rag=rag,
                ),
            ))
        return packets

    async def analyze_packets(
        self,
        packets: list[tuple[str, ContextPacket]],
        analysis: Analysis,
    ) -> list[AnalysisResult]:
        """조문들을 제한된 동시성으로 분석한다."""
        semaphore = asyncio.Semaphore(ARTICLE_CONCURRENCY)

        collected: list[TraceRecord] = []

        async def one(article_no: str, packet: ContextPacket) -> AnalysisResult | None:
            async with semaphore:
                runner = ChainRunner(llm=self.llm)
                result: AnalysisResult | None = None
                try:
                    outcome = await analyze_article(
                        runner,
                        packet,
                        analysis_id=analysis.analysis_id,
                        trace_id=analysis.trace_id,
                    )
                    result = outcome.result
                except Exception as exc:
                    # ER-002/ER-003: 조문 1건 실패가 분석 전체를 죽이지 않는다.
                    logger.warning(
                        "조문 분석 실패 law=%s article=%s err=%s",
                        packet.law.law_name, article_no, exc,
                    )
                finally:
                    # 실패한 호출의 기록이 더 중요하다. 성공 여부와 무관하게 남긴다.
                    collected.extend(
                        TraceRecord.of(
                            trace,
                            trace_id=analysis.trace_id,
                            analysis_id=analysis.analysis_id,
                            user_id=analysis.user_id,
                            law_id=packet.law.law_id,
                            article_no=article_no,
                        )
                        for trace in runner.traces
                    )
                return result

        done = await asyncio.gather(*(one(no, p) for no, p in packets))
        await self._trace_repo.save_many(collected)
        self._last_traces = collected
        return [result for result in done if result is not None]

    # ── 실행 ──────────────────────────────────────────────────────────

    async def run(self, analysis: Analysis, profile: Profile, *, max_laws: int = 3) -> Analysis:
        analysis = analysis.model_copy(
            update={"status": AnalysisStatus.RUNNING, "started_at": datetime.now(UTC)}
        )
        await self.analysis_repo.update(analysis)

        try:
            items = await self.collect(analysis, profile, max_laws=max_laws)
        except LawApiError as exc:
            logger.warning("법령 수집 실패 analysis=%s: %s", analysis.analysis_id, exc)
            return await self.fail(
                analysis, "법령 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."
            )
        except Exception as exc:
            logger.exception("법령 수집 중 예기치 못한 오류 analysis=%s", analysis.analysis_id)
            return await self.fail(analysis, "분석을 준비하지 못했습니다.", detail=str(exc))

        # 법령을 번갈아 가며 조문을 뽑아 총량 상한을 채운다. 한 법령이 상한을
        # 독식하면 다른 법령의 변화는 아예 보이지 않는다.
        per_law = [await self.build_packets(item, profile) for item in items]
        packets: list[tuple[str, ContextPacket]] = []
        for index in range(MAX_ARTICLES_PER_ANALYSIS):
            added = False
            for law_packets in per_law:
                if index < len(law_packets) and len(packets) < MAX_ARTICLES_PER_ANALYSIS:
                    packets.append(law_packets[index])
                    added = True
            if not added:
                break

        for item in items:
            await self.snapshot_repo.save(item.snapshot)

        self._last_traces = []
        all_results = await self.analyze_packets(packets, analysis)
        await self.result_repo.save_many(all_results)

        completed = analysis.model_copy(
            update={
                "status": AnalysisStatus.COMPLETED,
                "completed_at": datetime.now(UTC),
                "laws_examined": len(items),
                "articles_changed": len(packets),
                "counts": summarize(all_results),
                "snapshot_law_ids": [i.snapshot.law_id for i in items],
                "chain_calls": len(self._last_traces),
                "total_tokens": sum(
                    t.input_tokens + t.output_tokens for t in self._last_traces
                ),
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
