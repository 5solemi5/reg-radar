"""관측성 테스트 (NFR-009, 04 설계서 §11).

요구사항: 최소 요청 단위 latency, model, token/usage, error, trace 식별 가능.
"""

import pytest

from app.ai.chains.base import ChainRunner, ChainTrace, extract_usage
from app.repositories.traces import (
    InMemoryTraceRepository,
    NullTraceRepository,
    TraceRecord,
)


class FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        if usage_metadata is not None:
            self.usage_metadata = usage_metadata
        if response_metadata is not None:
            self.response_metadata = response_metadata


class TestUsageExtraction:
    def test_usage_metadata에서_추출(self):
        message = FakeMessage(usage_metadata={"input_tokens": 1200, "output_tokens": 340})
        assert extract_usage(message) == (1200, 340)

    def test_response_metadata_fallback(self):
        """provider마다 담기는 위치가 다르다."""
        message = FakeMessage(
            response_metadata={"token_usage": {"prompt_tokens": 900, "completion_tokens": 120}}
        )
        assert extract_usage(message) == (900, 120)

    def test_사용량을_못_찾으면_0(self):
        """사용량을 몰라도 분석은 성립한다. 실패로 취급하지 않는다."""
        assert extract_usage(FakeMessage()) == (0, 0)
        assert extract_usage(None) == (0, 0)


class TestChainTrace:
    def test_총_토큰_계산(self):
        trace = ChainTrace("C3", "gpt-4o", 1200, ok=True, input_tokens=900, output_tokens=100)
        assert trace.total_tokens == 1000

    def test_로그에_필요한_항목이_모두_있다(self):
        """NFR-009가 요구하는 관측 항목."""
        trace = ChainTrace("C4", "gpt-4o", 800, ok=False, error="timeout")
        log = trace.to_log()
        assert set(log) >= {"chain", "model", "latency_ms", "ok", "input_tokens", "error"}

    def test_러너가_누적한다(self):
        runner = ChainRunner(llm=None)
        runner.traces = [
            ChainTrace("C3", "gpt-4o", 1000, ok=True, input_tokens=500, output_tokens=50),
            ChainTrace("C4", "gpt-4o", 1500, ok=True, input_tokens=700, output_tokens=80),
        ]
        assert runner.total_latency_ms == 2500
        assert runner.total_tokens == 1330


class TestTraceRecord:
    def test_ChainTrace에서_변환(self):
        trace = ChainTrace("C5", "gpt-4o", 900, ok=True, input_tokens=400, output_tokens=60)
        record = TraceRecord.of(
            trace, trace_id="t-1", analysis_id="a-1", user_id="u-1",
            law_id="001872", article_no="제60조",
        )
        assert record.chain == "C5"
        assert record.input_tokens == 400
        assert record.law_id == "001872"

    def test_에러_메시지_길이를_제한한다(self):
        """예외 메시지에 프롬프트가 섞여 들어올 수 있다."""
        trace = ChainTrace("C4", "gpt-4o", 100, ok=False, error="x" * 2000)
        record = TraceRecord.of(trace, trace_id="t", analysis_id=None, user_id="u")
        assert len(record.error) == 500

    def test_프롬프트나_응답_원문을_담지_않는다(self):
        """04 설계서 §9. 관측성 도구가 개인정보 저장소가 되면 안 된다."""
        fields = set(TraceRecord.__dataclass_fields__)
        assert not ({"prompt", "response", "messages", "original_text"} & fields)


class TestTraceRepository:
    async def test_저장후_집계(self):
        repo = InMemoryTraceRepository()
        await repo.save_many([
            TraceRecord("t1", "a1", "u1", "C3", "gpt-4o", 1000, True,
                        input_tokens=500, output_tokens=50),
            TraceRecord("t1", "a1", "u1", "C4", "gpt-4o", 2000, True,
                        input_tokens=700, output_tokens=80),
            TraceRecord("t1", "a1", "u1", "C5", "gpt-4o", 500, False, error="timeout"),
        ])
        summary = await repo.summarize("a1", "u1")
        assert summary.chain_calls == 3
        assert summary.failures == 1
        assert summary.total_tokens == 1330
        assert summary.total_latency_ms == 3500
        assert summary.slowest_call_ms == 2000

    async def test_남의_분석은_집계되지_않는다(self):
        """NFR-007은 관측 기록에도 적용된다."""
        repo = InMemoryTraceRepository()
        await repo.save_many([TraceRecord("t1", "a1", "u1", "C3", "m", 100, True)])
        assert (await repo.summarize("a1", "u2")).chain_calls == 0

    async def test_기록이_없으면_빈_집계(self):
        assert (await InMemoryTraceRepository().summarize("nope", "u1")).chain_calls == 0

    async def test_Null저장소는_조용히_통과한다(self):
        repo = NullTraceRepository()
        await repo.save_many([TraceRecord("t", None, "u", "C3", "m", 1, True)])
        assert (await repo.summarize("a", "u")).chain_calls == 0


class TestFailuresAreRecorded:
    """실패한 호출의 기록이 더 중요하다."""

    async def test_실패도_기록된다(self):
        repo = InMemoryTraceRepository()
        await repo.save_many([
            TraceRecord("t1", "a1", "u1", "C4", "gpt-4o", 30000, False,
                        error="Request timed out"),
        ])
        summary = await repo.summarize("a1", "u1")
        assert summary.failures == 1
        assert repo.records[0].error == "Request timed out"


@pytest.mark.parametrize("field", ["chain_calls", "total_tokens"])
def test_분석_엔티티가_관측_필드를_갖는다(field):
    from app.domain.entities import Analysis

    assert field in Analysis.model_fields
