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

from app.ai.llm import LlmGateway
from app.ai.prompts import SYSTEM_COMMON

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ChainExecutionError(RuntimeError):
    """LLM 호출 또는 구조화 출력 파싱 실패 (ER-002, ER-003)."""


@dataclass
class ChainTrace:
    """체인 1회 실행의 관측 기록 (NFR-009)."""

    chain: str
    model: str
    latency_ms: int
    ok: bool
    error: str | None = None


@dataclass
class ChainRunner:
    """체인 실행 + trace 수집."""

    llm: LlmGateway
    traces: list[ChainTrace] = field(default_factory=list)

    async def invoke(self, *, chain: str, prompt: str, schema: type[T]) -> T:
        started = time.perf_counter()
        messages = [SystemMessage(content=SYSTEM_COMMON), HumanMessage(content=prompt)]
        try:
            result = await self.llm.structured(schema).ainvoke(messages)
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            self.traces.append(
                ChainTrace(chain, self.llm.model_name, elapsed, ok=False, error=str(exc))
            )
            logger.warning("체인 실패: chain=%s err=%s", chain, exc)
            raise ChainExecutionError(f"{chain} 실행 실패: {exc}") from exc

        elapsed = int((time.perf_counter() - started) * 1000)
        self.traces.append(ChainTrace(chain, self.llm.model_name, elapsed, ok=True))

        if not isinstance(result, schema):
            # with_structured_output이 dict를 돌려주는 provider 대비
            result = schema.model_validate(result)
        return result

    @property
    def total_latency_ms(self) -> int:
        return sum(t.latency_ms for t in self.traces)
