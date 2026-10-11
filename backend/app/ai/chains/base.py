"""체인 공통 실행 경로.

ER-003: Structured Output 파싱 실패는 예외로 드러나야 하며 임의 보정하지 않는다.
NFR-009: 모든 호출의 model/latency/성공여부를 기록할 수 있게 한 곳을 지난다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.ai.cassette import Cassette, CassetteMode, call_key
from app.ai.llm import LlmGateway
from app.ai.prompts import SYSTEM_COMMON

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ChainExecutionError(RuntimeError):
    """LLM 호출 또는 구조화 출력 파싱 실패 (ER-002, ER-003)."""


@dataclass
class ChainTrace:
    """체인 1회 실행의 관측 기록 (NFR-009).

    latency, model, token/usage, error를 모두 담는다. 토큰은 비용 추적과
    프롬프트 비대화 감지에 쓰이므로 없으면 운영에서 원인을 못 찾는다.
    """

    chain: str
    model: str
    latency_ms: int
    ok: bool
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    retried: bool = False
    attempt: int = 0  # REJECT 재생성 회차 (0 = 첫 시도). 문서 11 §11-4
    prompt_version: str | None = None  # app/core/pricing.py::prompt_version

    @property
    def cost_usd(self) -> float | None:
        from app.core.pricing import cost_usd

        return cost_usd(self.model, self.input_tokens, self.output_tokens)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_log(self) -> dict:
        return {
            "chain": self.chain,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "attempt": self.attempt,
            "prompt_version": self.prompt_version,
            "error": self.error,
        }


def extract_usage(raw) -> tuple[int, int]:
    """AIMessage에서 토큰 사용량을 꺼낸다.

    provider마다 담기는 위치가 달라 두 곳을 본다. 못 찾으면 0으로 두되
    실패로 취급하지 않는다 — 사용량을 몰라도 분석은 성립한다.
    """
    usage = getattr(raw, "usage_metadata", None)
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))

    metadata = getattr(raw, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    if isinstance(token_usage, dict):
        return (
            int(token_usage.get("prompt_tokens", 0)),
            int(token_usage.get("completion_tokens", 0)),
        )
    return 0, 0


@dataclass
class ChainRunner:
    """체인 실행 + trace 수집."""

    llm: LlmGateway
    traces: list[ChainTrace] = field(default_factory=list)
    cassette: Cassette | None = None  # 평가 전용 녹화·재생 (app/ai/cassette.py)
    attempt: int = 0  # REJECT 재생성 회차. analyze_article이 올린다

    def _record(self, trace: ChainTrace) -> None:
        from app.core.pricing import prompt_version

        trace.attempt = self.attempt
        trace.prompt_version = prompt_version(trace.chain)
        self.traces.append(trace)

    async def invoke(self, *, chain: str, prompt: str, schema: type[T]) -> T:
        started = time.perf_counter()
        messages = [SystemMessage(content=SYSTEM_COMMON), HumanMessage(content=prompt)]

        key = None
        if self.cassette is not None and self.cassette.active:
            key = call_key(
                chain=chain, model=self.cassette.model, system=SYSTEM_COMMON,
                prompt=prompt, schema=schema,
            )
            rec = None
            if self.cassette.mode is CassetteMode.REPLAY:
                # LLM을 부르지 않는다(키도 필요 없다). 녹화가 없으면 CassetteMiss로 실패한다.
                rec = self.cassette.lookup(key)
            else:
                # RECORD: 녹화된 키는 재사용, 같은 키를 누가 부르는 중이면 그 결과를 기다린다
                rec = self.cassette.peek(key)
                if rec is None:
                    waiting = self.cassette.claim(key)
                    if waiting is not None:
                        rec = await waiting
                if rec is not None:
                    self.cassette.hits += 1
            if rec is not None:
                return self._from_recording(chain, schema, rec)

        try:
            envelope = await self.llm.structured_with_usage(schema).ainvoke(messages)
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            trace = ChainTrace(
                chain, self.llm.model_name, elapsed, ok=False, error=str(exc)
            )
            self._record(trace)
            logger.warning("체인 실패 %s", trace.to_log())
            message = f"{chain} 실행 실패: {exc}"
            self._record_failure(key, message, 0, 0, elapsed)
            raise ChainExecutionError(message) from exc

        elapsed = int((time.perf_counter() - started) * 1000)

        # include_raw=True면 {"raw", "parsed", "parsing_error"} 형태로 온다.
        if isinstance(envelope, dict) and "parsed" in envelope:
            raw, parsed = envelope.get("raw"), envelope.get("parsed")
            parsing_error = envelope.get("parsing_error")
            input_tokens, output_tokens = extract_usage(raw)
        else:
            raw, parsed, parsing_error = None, envelope, None
            input_tokens = output_tokens = 0

        if parsing_error is not None or parsed is None:
            # ER-003: 파싱 실패를 임의 보정하지 않고 실패로 드러낸다.
            trace = ChainTrace(
                chain, self.llm.model_name, elapsed, ok=False,
                error=str(parsing_error or "구조화 출력 없음"),
                input_tokens=input_tokens, output_tokens=output_tokens,
            )
            self._record(trace)
            logger.warning("구조화 출력 실패 %s", trace.to_log())
            message = f"{chain} 구조화 출력 실패: {parsing_error}"
            self._record_failure(key, message, input_tokens, output_tokens, elapsed)
            raise ChainExecutionError(message)

        trace = ChainTrace(
            chain, self.llm.model_name, elapsed, ok=True,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        self._record(trace)
        logger.info("체인 완료 %s", trace.to_log())

        if not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)
        if key is not None and self.cassette.mode is CassetteMode.RECORD:
            rec = self.cassette.store(key, parsed, input_tokens, output_tokens, elapsed)
            self.cassette.resolve(key, rec)
        return parsed

    def _record_failure(self, key, message, input_tokens, output_tokens, elapsed) -> None:
        cassette = self.cassette
        if key is not None and cassette is not None and cassette.mode is CassetteMode.RECORD:
            rec = cassette.store(key, None, input_tokens, output_tokens, elapsed, error=message)
            cassette.resolve(key, rec)

    def _from_recording(self, chain: str, schema: type[T], rec) -> T:
        """녹화된 결과를 실제 호출처럼 돌려준다 — 실패도 녹화된 그대로 재현한다."""
        ok = rec.error is None
        self._record(
            ChainTrace(
                chain, self.cassette.model, rec.latency_ms, ok=ok, error=rec.error,
                input_tokens=rec.input_tokens, output_tokens=rec.output_tokens,
            )
        )
        if not ok:
            raise ChainExecutionError(rec.error)
        return schema.model_validate(rec.parsed)

    @property
    def total_latency_ms(self) -> int:
        # LLM 호출 시간만 더한다. 규칙 검증(C6) 시간은 실측이라, 녹화 재생에서 이 값이
        # 실행마다 흔들리면 재생 회귀 기준이 깨진다. C6 시간은 trace 행에 따로 남는다.
        return sum(t.latency_ms for t in self.traces if t.model != "rules")

    @property
    def total_tokens(self) -> int:
        return sum(t.total_tokens for t in self.traces)
