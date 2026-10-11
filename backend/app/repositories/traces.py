"""AI 실행 추적 저장소 (NFR-009, 04 설계서 §11).

프롬프트 원문과 모델 응답 전문은 저장하지 않는다. 사용자 프로필과 법령 원문이
그대로 남으면 관측성 도구가 개인정보 저장소가 된다 (04 설계서 §9).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.ai.chains.base import ChainTrace
from app.repositories.db import Database

logger = logging.getLogger(__name__)


@dataclass
class TraceRecord:
    trace_id: str
    analysis_id: str | None
    user_id: str
    chain: str
    model: str
    latency_ms: int
    ok: bool
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    law_id: str | None = None
    article_no: str | None = None
    cost_usd: float | None = None
    prompt_version: str | None = None
    attempt: int = 0

    @property
    def is_rule(self) -> bool:
        """규칙 검증(C6) 행. LLM 호출 수·실패 수에 세지 않는다."""
        return self.model == "rules"

    @classmethod
    def of(
        cls,
        trace: ChainTrace,
        *,
        trace_id: str,
        analysis_id: str | None,
        user_id: str,
        law_id: str | None = None,
        article_no: str | None = None,
    ) -> TraceRecord:
        return cls(
            trace_id=trace_id,
            analysis_id=analysis_id,
            user_id=user_id,
            chain=trace.chain,
            model=trace.model,
            latency_ms=trace.latency_ms,
            ok=trace.ok,
            # 예외 메시지에 프롬프트가 섞여 들어올 수 있어 길이를 제한한다.
            error=trace.error[:500] if trace.error else None,
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            law_id=law_id,
            article_no=article_no,
            cost_usd=trace.cost_usd,
            prompt_version=trace.prompt_version,
            attempt=trace.attempt,
        )


@dataclass
class TraceSummary:
    chain_calls: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: int = 0
    slowest_call_ms: int = 0
    cost_usd: float = 0.0
    validator_rejects: int = 0
    regenerations: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TraceRepository(Protocol):
    async def save_many(self, records: list[TraceRecord]) -> None: ...
    async def summarize(self, analysis_id: str, user_id: str) -> TraceSummary: ...


class InMemoryTraceRepository:
    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    async def save_many(self, records: list[TraceRecord]) -> None:
        self.records.extend(records)

    async def summarize(self, analysis_id: str, user_id: str) -> TraceSummary:
        mine = [
            r for r in self.records
            if r.analysis_id == analysis_id and r.user_id == user_id
        ]
        rows = [r for r in mine if not r.is_rule]
        rules = [r for r in mine if r.is_rule]
        if not mine:
            return TraceSummary()
        return TraceSummary(
            chain_calls=len(rows),
            failures=sum(1 for r in rows if not r.ok),
            input_tokens=sum(r.input_tokens for r in rows),
            output_tokens=sum(r.output_tokens for r in rows),
            total_latency_ms=sum(r.latency_ms for r in mine),
            slowest_call_ms=max(r.latency_ms for r in mine),
            cost_usd=round(sum(r.cost_usd or 0.0 for r in rows), 6),
            validator_rejects=sum(1 for r in rules if not r.ok),
            regenerations=sum(1 for r in rules if r.attempt > 0),
        )

    def clear(self) -> None:
        self.records.clear()


class PostgresTraceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_many(self, records: list[TraceRecord]) -> None:
        if not records:
            return
        try:
            await self._db.executemany(
                """
                INSERT INTO ai_traces (
                    trace_id, analysis_id, user_id, law_id, article_no,
                    chain, model, latency_ms, ok, error, input_tokens, output_tokens,
                    cost_usd, prompt_version, attempt
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15
                )
                """,
                [
                    (
                        r.trace_id, r.analysis_id, r.user_id, r.law_id, r.article_no,
                        r.chain, r.model, r.latency_ms, r.ok, r.error,
                        r.input_tokens, r.output_tokens,
                        r.cost_usd, r.prompt_version, r.attempt,
                    )
                    for r in records
                ],
            )
        except Exception as exc:
            # 관측 기록 실패가 분석 실패로 번지면 안 된다. 관측은 부수 효과다.
            logger.warning("trace 저장 실패 (분석은 계속): %s", exc)

    async def summarize(self, analysis_id: str, user_id: str) -> TraceSummary:
        try:
            row = await self._db.fetchrow(
                """
                SELECT count(*) AS all_rows,
                       count(*) FILTER (WHERE model <> 'rules') AS chain_calls,
                       count(*) FILTER (WHERE NOT ok AND model <> 'rules') AS failures,
                       coalesce(sum(input_tokens), 0) AS input_tokens,
                       coalesce(sum(output_tokens), 0) AS output_tokens,
                       coalesce(sum(latency_ms), 0) AS total_latency_ms,
                       coalesce(max(latency_ms), 0) AS slowest_call_ms,
                       coalesce(sum(cost_usd), 0) AS cost_usd,
                       count(*) FILTER (WHERE model = 'rules' AND NOT ok) AS validator_rejects,
                       count(*) FILTER (WHERE model = 'rules' AND attempt > 0) AS regenerations
                FROM ai_traces
                WHERE analysis_id = $1::uuid AND user_id = $2
                """,
                analysis_id,
                user_id,
            )
        except Exception as exc:
            logger.warning("trace 집계 실패: %s", exc)
            return TraceSummary()
        if row is None or not row["all_rows"]:
            return TraceSummary()
        return TraceSummary(
            chain_calls=int(row["chain_calls"]),
            failures=int(row["failures"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            total_latency_ms=int(row["total_latency_ms"]),
            slowest_call_ms=int(row["slowest_call_ms"]),
            cost_usd=float(row["cost_usd"]),
            validator_rejects=int(row["validator_rejects"]),
            regenerations=int(row["regenerations"]),
        )


class NullTraceRepository:
    """관측 저장이 구성되지 않은 환경용."""

    async def save_many(self, records: list[TraceRecord]) -> None:
        return None

    async def summarize(self, analysis_id: str, user_id: str) -> TraceSummary:
        return TraceSummary()
